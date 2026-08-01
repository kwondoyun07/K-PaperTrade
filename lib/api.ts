import { NextResponse } from "next/server";

export const jerr = (msg: string, status = 400) =>
  NextResponse.json({ error: msg }, { status });

export const qs = (req: Request) => new URL(req.url).searchParams;

export const nowKst = () =>
  new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 16).replace("T", " ");

export const todayKst = () => nowKst().slice(0, 10);
