import type { CSSProperties } from "react";

export function setupCanvas(cv: HTMLCanvasElement) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.offsetWidth;
  const H = cv.offsetHeight;
  if (!W) return null;
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  if (!g) return null;
  g.scale(dpr, dpr);
  g.font = "11px Pretendard, sans-serif";
  return { g, W, H };
}

// 세그먼트 버튼 (기간·배속·매수/매도 탭 공용)
export function seg(active: boolean, accent?: string): CSSProperties {
  return {
    height: 28,
    padding: "0 12px",
    borderRadius: 7,
    border: "none",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
    background: active ? accent ?? "#26262E" : "transparent",
    color: active ? (accent ? "#fff" : "#E8E8EC") : "#8B8D98",
  };
}
