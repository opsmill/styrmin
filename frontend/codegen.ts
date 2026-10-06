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
        enumsAsTypes: true,
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
          BigInt: "number",
        },
      },
    },
  },
  ignoreNoDocuments: true,
  hooks: {
    afterAllFileWrite: [
      "node -e \"const fs=require('fs');const f='src/generated/graphql.ts';const c=fs.readFileSync(f,'utf8');fs.writeFileSync(f,c.replace('import { useMutation, useQuery, UseMutationOptions, UseQueryOptions }','import { useMutation, useQuery, type UseMutationOptions, type UseQueryOptions }'))\"",
    ],
  },
};

export default config;
