import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: "../schema.graphql",
  documents: "src/graphql/**/*.graphql",
  generates: {
    "src/generated/graphql.ts": {
      plugins: [
        "typescript",
        "typescript-operations",
        "typescript-urql",
      ],
      config: {
        withHooks: true,
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
