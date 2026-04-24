import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { graphqlFetcher, GraphQLTransportError } from "./graphql-fetcher";

const QUERY = "query Test { ok }";

function mockFetchResponse(
  body: string,
  init: { status?: number; statusText?: string; contentType?: string } = {},
): void {
  const { status = 200, statusText = "OK", contentType } = init;
  const headers = new Headers();
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  const response = new Response(body, { status, statusText, headers });
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(response)),
  );
}

describe("graphqlFetcher", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
});
