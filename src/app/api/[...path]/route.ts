import type { NextRequest } from 'next/server';

const BACKEND_URL = process.env.RECOVERAI_API_BASE_URL || 'http://127.0.0.1:8000';

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = new URL(`/api/${path.join('/')}`, BACKEND_URL);
  target.search = request.nextUrl.search;

  try {
    const response = await fetch(target, { headers: { accept: 'application/json' }, cache: 'no-store' });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        'content-type': response.headers.get('content-type') || 'application/json',
      },
    });
  } catch {
    return Response.json(
      { detail: 'RecoverAI backend is unavailable. Start FastAPI on port 8000.' },
      { status: 502 },
    );
  }
}
