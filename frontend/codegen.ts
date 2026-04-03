import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: "../schema.graphql",
  documents: "src/graphql/**/*.graphql",
  generates: {
    "src/generated/graphql.ts": {
      plugins: [
        "typescript",
        "typescript-operations",
        "typescript-react-query",
      ],
      config: {
        reactQueryVersion: 5,
        fetcher: {
          func: "../lib/graphql-fetcher#graphqlFetcher",
        },
        exposeQueryKeys: true,
        exposeFetcher: false,
        addSuspenseQuery: false,
        errorType: "Error",
        scalars: {
          UUID: "string",
          JSON: "Record<string, unknown>",
        },
      },
    },
  },
  ignoreNoDocuments: true,
};

export default config;
