import type { NextRequest } from 'next/server';

const BACKEND_URL = process.env.RECOVERAI_API_BASE_URL || 'http://127.0.0.1:8000';

async function proxy(request: NextRequest, path: string[]) {
  const target = new URL(`/api/${path.join('/')}`, BACKEND_URL);
  target.search = request.nextUrl.search;

  const headers: Record<string, string> = {};
  // Forward relevant headers including webhook signature
  for (const [k, v] of request.headers.entries()) {
    if (k.toLowerCase().startsWith('x-razorpay') || k.toLowerCase() === 'content-type' || k.toLowerCase() === 'accept') {
      headers[k] = v;
    }
  }
  // Ensure content-type fallback
  if (!headers['content-type'] && !headers['Content-Type']) {
    const ct = request.headers.get('content-type');
    if (ct) headers['content-type'] = ct;
  }

  const method = request.method;
  let body: string | undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    const raw = await request.text();
    body = raw || undefined;
    if (body && !headers['content-type'] && !headers['Content-Type']) {
      headers['content-type'] = 'application/json';
    }
  }

  try {
    const response = await fetch(target, {
      method,
      headers: { accept: 'application/json', ...headers },
      body,
      cache: 'no-store',
    });
    const respBody = await response.text();
    return new Response(respBody, {
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

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
export async function PUT(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
export async function PATCH(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
export async function DELETE(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(request, path);
}
