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

    const json = await response.json();

    if (json.errors) {
      const message = json.errors[0]?.message ?? "Unknown GraphQL error";
      throw new Error(message);
    }

    return json.data as TData;
  };
}
