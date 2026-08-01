import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "K-PaperTrade",
  description: "국내주식 1분봉 모의투자",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body>
        {children}
        <footer className="disclaimer">
          본 서비스는 모의투자·교육용 시뮬레이터입니다. 실제 매매가 이루어지지
          않으며 투자 권유가 아닙니다. 현재 화면은 더미 데이터로 동작합니다.
        </footer>
      </body>
    </html>
  );
}
