import { Toast } from "@base-ui/react/toast";

/**
 * Raise a transient toast from any component rendered under the app-wide
 * `<Toaster>` (see components/ui/toast.tsx). Thin alias over Base UI's toast
 * manager: `const toast = useToast(); toast.add({ title, description, type })`.
 */
export const useToast = Toast.useToastManager;
