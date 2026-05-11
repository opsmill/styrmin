import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  graphqlFetcher,
  GraphQLTransportError,
  GraphQLOperationError,
  UnauthenticatedError,
  ForbiddenError,
  setUnauthenticatedHandler,
} from "./graphql-fetcher";

const QUERY = "query Test { ok }";

function mockFetchResponse(
  body: string,
  init: { status?: number; statusText?: string; contentType?: string } = {},
): ReturnType<typeof vi.fn> {
  const { status = 200, statusText = "OK", contentType } = init;
  const headers = new Headers();
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  const response = new Response(body, { status, statusText, headers });
  const fetchMock = vi.fn(() => Promise.resolve(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("graphqlFetcher", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setUnauthenticatedHandler(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthenticatedHandler(null);
  });

  it("returns data on 2xx JSON response", async () => {
    mockFetchResponse(JSON.stringify({ data: { ok: true } }), {
      contentType: "application/json",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await expect(fetcher()).resolves.toEqual({ ok: true });
  });

  it("throws a GraphQL error for a 2xx response with errors", async () => {
    mockFetchResponse(JSON.stringify({ errors: [{ message: "boom" }] }), {
      contentType: "application/json",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await expect(fetcher()).rejects.toThrow("boom");
  });

  it("surfaces GraphQL errors from a non-2xx JSON response", async () => {
    mockFetchResponse(JSON.stringify({ errors: [{ message: "bad input" }] }), {
      status: 400,
      statusText: "Bad Request",
      contentType: "application/json",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await expect(fetcher()).rejects.toThrow("bad input");
  });

  it("throws GraphQLTransportError for a non-2xx non-JSON response", async () => {
    mockFetchResponse("<html><body>Bad Gateway</body></html>", {
      status: 502,
      statusText: "Bad Gateway",
      contentType: "text/html",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    const promise = fetcher();
    await expect(promise).rejects.toBeInstanceOf(GraphQLTransportError);
    await expect(promise).rejects.toMatchObject({
      status: 502,
      statusText: "Bad Gateway",
    });
  });

  it("throws GraphQLTransportError for an empty 5xx response body", async () => {
    mockFetchResponse("", {
      status: 500,
      statusText: "Internal Server Error",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    const promise = fetcher();
    await expect(promise).rejects.toBeInstanceOf(GraphQLTransportError);
    await expect(promise).rejects.toMatchObject({ status: 500 });
  });

  it("throws GraphQLTransportError for a 2xx response with malformed JSON", async () => {
    mockFetchResponse("not-json-at-all", {
      status: 200,
      statusText: "OK",
      contentType: "application/json",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await expect(fetcher()).rejects.toBeInstanceOf(GraphQLTransportError);
  });

  it("throws GraphQLTransportError for a 2xx response missing data and errors", async () => {
    mockFetchResponse(JSON.stringify({}), {
      contentType: "application/json",
    });
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await expect(fetcher()).rejects.toBeInstanceOf(GraphQLTransportError);
  });

  it("sends credentials: 'include' on every request", async () => {
    const fetchMock = mockFetchResponse(
      JSON.stringify({ data: { ok: true } }),
      { contentType: "application/json" },
    );
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    await fetcher();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0]!;
    expect((init as RequestInit).credentials).toBe("include");
  });

  it("invokes the unauthenticated handler and throws UnauthenticatedError on UNAUTHENTICATED", async () => {
    mockFetchResponse(
      JSON.stringify({
        errors: [
          {
            message: "Authentication required",
            extensions: { code: "UNAUTHENTICATED" },
          },
        ],
      }),
      { contentType: "application/json" },
    );
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    const promise = fetcher();
    await expect(promise).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("throws ForbiddenError without invoking the unauthenticated handler on FORBIDDEN", async () => {
    mockFetchResponse(
      JSON.stringify({
        errors: [
          { message: "Forbidden", extensions: { code: "FORBIDDEN" } },
        ],
      }),
      { contentType: "application/json" },
    );
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    const promise = fetcher();
    await expect(promise).rejects.toBeInstanceOf(ForbiddenError);
    expect(handler).not.toHaveBeenCalled();
  });

  it("preserves an unknown error code on GraphQLOperationError", async () => {
    mockFetchResponse(
      JSON.stringify({
        errors: [
          {
            message: "Already exists",
            extensions: { code: "DUPLICATE_USERNAME" },
          },
        ],
      }),
      { contentType: "application/json" },
    );
    const fetcher = graphqlFetcher<{ ok: boolean }, undefined>(QUERY);
    const promise = fetcher();
    await expect(promise).rejects.toBeInstanceOf(GraphQLOperationError);
    await expect(promise).rejects.toMatchObject({
      code: "DUPLICATE_USERNAME",
      graphqlMessage: "Already exists",
    });
  });
});
