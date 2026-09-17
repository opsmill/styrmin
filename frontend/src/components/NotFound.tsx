import { useDocumentTitle } from "@/hooks/use-document-title";

export function NotFound() {
  useDocumentTitle("Page not found");
  return <div>Page not found</div>;
}
