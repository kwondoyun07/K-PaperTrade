"""분봉 parquet 저장 + GitHub Release 업로드.

원칙(핸드오프 §2.3): 분봉 원본은 DB가 아니라 일자별 parquet 1파일(전 종목
통합, zstd 압축) → GitHub Release 자산(태그 minute-YYYY-MM)으로 보관.
Turso 무료 쓰기 한도(월 1,000만 행)를 분봉이 초과하기 때문.
"""

import logging
import shutil
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from providers.base import MinuteBar

log = logging.getLogger(__name__)

SCHEMA = pa.schema(
    [
        ("ticker", pa.string()),
        ("ts", pa.string()),  # 'YYYY-MM-DD HH:MM' KST
        ("open", pa.int64()),
        ("high", pa.int64()),
        ("low", pa.int64()),
        ("close", pa.int64()),
        ("volume", pa.int64()),
    ]
)


class MinuteParquetStore:
    """일자별 parquet 스트리밍 기록.

    티커를 정렬 순서로 순회하며 add()하면 파일도 (ticker, ts) 정렬 상태가 된다.
    버퍼가 flush_rows를 넘으면 record batch로 내려써서 메모리 상한을 유지한다.
    """

    def __init__(self, out_dir: str | Path, flush_rows: int = 200_000):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.flush_rows = flush_rows
        self.rows = 0
        self._writers: dict[str, pq.ParquetWriter] = {}
        self._buf: dict[str, list[MinuteBar]] = {}
        self._buf_rows = 0

    def add(self, bars: list[MinuteBar]) -> None:
        for b in bars:
            self._buf.setdefault(b.ts[:10], []).append(b)
        self._buf_rows += len(bars)
        self.rows += len(bars)
        if self._buf_rows >= self.flush_rows:
            self.flush()

    def flush(self) -> None:
        for d, bars in self._buf.items():
            w = self._writers.get(d)
            if w is None:
                w = pq.ParquetWriter(
                    self.out_dir / f"minute-{d}.parquet", SCHEMA, compression="zstd"
                )
                self._writers[d] = w
            table = pa.Table.from_pydict(
                {
                    "ticker": [b.ticker for b in bars],
                    "ts": [b.ts for b in bars],
                    "open": [b.open for b in bars],
                    "high": [b.high for b in bars],
                    "low": [b.low for b in bars],
                    "close": [b.close for b in bars],
                    "volume": [b.volume for b in bars],
                },
                schema=SCHEMA,
            )
            w.write_table(table)
        self._buf.clear()
        self._buf_rows = 0

    def close(self) -> list[Path]:
        self.flush()
        for w in self._writers.values():
            w.close()
        return sorted(self.out_dir / f"minute-{d}.parquet" for d in self._writers)


def _existing_asset_size(base: list[str], tag: str, name: str) -> int | None:
    r = subprocess.run(
        base + ["release", "view", tag, "--json", "assets",
                "--jq", f'.assets[] | select(.name == "{name}") | .size'],
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        return None
    try:
        return int(out.splitlines()[0])
    except ValueError:
        return None


def upload_release(files: list[Path], repo: str | None = None) -> None:
    """gh CLI로 Release 자산 업로드. 태그는 파일명에서 유도(minute-YYYY-MM).

    - 같은 이름 자산은 --clobber로 교체하므로 재실행 멱등.
    - 단, 기존 자산보다 5% 이상 작은 파일은 결손 수집(부분 실패)으로 보고
      덮어쓰기를 거부한다 — 완전본 보호. parquet Release가 분봉의 유일한
      영구 저장소이므로 last-writer-wins로 완전본을 잃으면 복구 불가.
    - GitHub Actions에서는 GH_TOKEN 자동 주입(contents: write 필요).
      로컬에서 원격 저장소를 지정하려면 repo 인자 또는 GH_REPO env 사용.
    """
    if shutil.which("gh") is None:
        raise RuntimeError("gh CLI가 없어 Release 업로드 불가 — --upload 없이 실행하거나 gh 설치")
    base = ["gh"] + (["-R", repo] if repo else [])
    for f in files:
        tag = "minute-" + f.stem.removeprefix("minute-")[:7]  # minute-2026-08
        # 태그가 이미 있으면 create는 실패 — 정상 경로이므로 debug로만 남김
        r = subprocess.run(
            base + ["release", "create", tag, "--title", tag, "--notes", "KRX 1분봉 parquet"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log.debug("release create %s: %s", tag, (r.stderr or "").strip())
        prev = _existing_asset_size(base, tag, f.name)
        size = f.stat().st_size
        if prev is not None and size < prev * 0.95:
            raise RuntimeError(
                f"{f.name}: 새 파일({size}B)이 기존 자산({prev}B)보다 5%+ 작음 — "
                "결손 수집 의심, 덮어쓰기 거부"
            )
        try:
            subprocess.run(
                base + ["release", "upload", tag, str(f), "--clobber"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"release upload 실패({tag}): {(e.stderr or '').strip()}") from e
        log.info("release 업로드: %s → %s%s", f.name, tag, " (기존 자산 교체)" if prev else "")
