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

export class GraphQLOperationError extends Error {
  readonly code: string;
  readonly graphqlMessage: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "GraphQLOperationError";
    this.code = code;
    this.graphqlMessage = message;
  }
}

export class UnauthenticatedError extends GraphQLOperationError {
  constructor(message: string) {
    super("UNAUTHENTICATED", message);
    this.name = "UnauthenticatedError";
  }
}

export class ForbiddenError extends GraphQLOperationError {
  constructor(message: string) {
    super("FORBIDDEN", message);
    this.name = "ForbiddenError";
  }
}

type UnauthenticatedHandler = () => void;

let unauthenticatedHandler: UnauthenticatedHandler | null = null;

export function setUnauthenticatedHandler(
  cb: UnauthenticatedHandler | null,
): void {
  unauthenticatedHandler = cb;
}

type GraphQLErrorShape = {
  message?: string;
  extensions?: { code?: string } & Record<string, unknown>;
};

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

function throwForGraphQLError(error: GraphQLErrorShape): never {
  const message = error.message ?? "Unknown GraphQL error";
  const code = error.extensions?.code;
  if (code === "UNAUTHENTICATED") {
    unauthenticatedHandler?.();
    throw new UnauthenticatedError(message);
  }
  if (code === "FORBIDDEN") {
    throw new ForbiddenError(message);
  }
  if (typeof code === "string" && code.length > 0) {
    throw new GraphQLOperationError(code, message);
  }
  throw new GraphQLOperationError("UNKNOWN", message);
}

export function graphqlFetcher<TData, TVariables>(
  query: string,
  variables?: TVariables,
): () => Promise<TData> {
  return async () => {
    const response = await fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ query, variables }),
    });

    const body = await response.text();
    const json = parseJson<GraphQLResponse<TData>>(body);

    if (!response.ok) {
      if (json?.errors && json.errors.length > 0) {
        throwForGraphQLError(json.errors[0]!);
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
      throwForGraphQLError(json.errors[0]!);
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
