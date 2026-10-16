import type { Catalog, mutation } from "@/api";
import type { useAdminActions } from "./useAdminActions";
export type AdminPanelProps = {
  c: Catalog;
  save: typeof mutation;
  action: ReturnType<typeof useAdminActions>["action"];
};
