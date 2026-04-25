export class GraphQLTransportError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly body: string;

  constructor(status: number, statusText: string, body: string) {
    super(
      `GraphQL request failed: ${status} ${statusText || "HTTP error"}`.trim(),
    );
    this.name = "GraphQLTransportError";
    this.status = status;
    this.statusText = statusText;
    this.body = body;
  }
}

type GraphQLErrorShape = { message?: string };

type GraphQLResponse<TData> = {
  data?: TData;
  errors?: GraphQLErrorShape[];
};

function parseJson<T>(text: string): T | null {
  if (text.length === 0) {
    return null;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export function graphqlFetcher<TData, TVariables>(
  query: string,
  variables?: TVariables,
): () => Promise<TData> {
  return async () => {
    const response = await fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });

    const body = await response.text();
    const json = parseJson<GraphQLResponse<TData>>(body);

    if (!response.ok) {
      if (json?.errors && json.errors.length > 0) {
        const message = json.errors[0]?.message ?? "Unknown GraphQL error";
        throw new Error(message);
      }
      throw new GraphQLTransportError(
        response.status,
        response.statusText,
        body,
      );
    }

    if (json === null) {
      throw new GraphQLTransportError(
        response.status,
        response.statusText,
        body,
      );
    }

    if (json.errors && json.errors.length > 0) {
      const message = json.errors[0]?.message ?? "Unknown GraphQL error";
      throw new Error(message);
    }

    if (json.data === undefined) {
      throw new GraphQLTransportError(
        response.status,
        response.statusText,
        body,
      );
    }

    return json.data;
  };
}
