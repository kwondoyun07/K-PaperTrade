"use client";

import { useState } from "react";
import { UP } from "@/lib/format";

export default function Login() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    if (r.ok) window.location.href = "/";
    else setErr("비밀번호가 틀립니다");
  };

  return (
    <main style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <form onSubmit={submit} className="card" style={{ padding: 24, width: 320, display: "flex", flexDirection: "column", gap: 12 }}>
        <span style={{ fontWeight: 700, fontSize: 15 }}>K-PaperTrade</span>
        <input
          type="password"
          className="input"
          placeholder="비밀번호"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoFocus
        />
        {err && <span style={{ fontSize: 12, color: UP }}>{err}</span>}
        <button className="btnAccent" type="submit" style={{ justifyContent: "center" }}>
          로그인
        </button>
      </form>
    </main>
  );
}
