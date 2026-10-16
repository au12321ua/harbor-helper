import {
  mutation,
  type ValidPath,
  type WriteMethod,
  type WritePath,
  type WriteSpec,
} from "@/api";
import { useState } from "react";
import { toast } from "sonner";
export function useAdminActions(reload: () => Promise<void>) {
  const [saving, setSaving] = useState(false);
  async function save<
    M extends WriteMethod = "POST",
    P extends WritePath<M> = WritePath<M>,
  >(
    path: ValidPath<P, WriteSpec<M, P>>,
    value: WriteSpec<M, P>["request"],
    ...method: [M] extends ["POST"] ? [method?: M] : [method: M]
  ) {
    // Catalog refresh can remount editors. Keep every editor and its selectors
    // unavailable until both the mutation and refresh finish.
    setSaving(true);
    try {
      const result = await mutation<M, P>(path, value, ...method);
      await reload();
      return result;
    } finally {
      setSaving(false);
    }
  }
  async function action<
    M extends WriteMethod = "POST",
    P extends WritePath<M> = WritePath<M>,
  >(
    path: ValidPath<P, WriteSpec<M, P>>,
    value: WriteSpec<M, P>["request"],
    ...method: [M] extends ["POST"] ? [method?: M] : [method: M]
  ) {
    try {
      await save<M, P>(path, value, ...method);
      toast.success("已更新");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return { saving, save, action };
}
