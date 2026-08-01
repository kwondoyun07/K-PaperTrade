export default function Stub({ title }: { title: string }) {
  return (
    <section style={{ maxWidth: 1180 }}>
      <div
        style={{
          background: "#17171C",
          border: "1px dashed #2C2C36",
          borderRadius: 12,
          padding: "64px 0",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
        <span style={{ fontSize: 13, color: "#8B8D98" }}>
          대시보드·리플레이 확정 후 같은 디자인 시스템으로 확장 예정입니다
        </span>
      </div>
    </section>
  );
}
