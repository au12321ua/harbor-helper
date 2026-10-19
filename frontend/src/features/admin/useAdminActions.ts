import {
  mutation,
  type ValidPath,
  type WriteMethod,
  type WritePath,
  type WriteSpec,
} from "@/api";
import { useRef, useState } from "react";
import { toast } from "sonner";
export function useAdminActions(reload: () => Promise<void>) {
  const inFlight = useRef(false);
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
    if (inFlight.current) throw new Error("另一个保存正在进行，请稍后重试");
    inFlight.current = true;
    setSaving(true);
    try {
      const result = await mutation<M, P>(path, value, ...method);
      await reload();
      return result;
    } finally {
      inFlight.current = false;
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
