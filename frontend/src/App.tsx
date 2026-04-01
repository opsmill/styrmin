import { RouterProvider } from "@tanstack/react-router";
import { Provider } from "urql";
import { client } from "@/lib/urql";
import { router } from "@/router";

export default function App() {
  return (
    <Provider value={client}>
      <RouterProvider router={router} />
    </Provider>
  );
}
