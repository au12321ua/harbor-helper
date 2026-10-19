import { useState } from "react";
import {
  browserZone,
  setTimezone,
  timezone,
  useTimezone,
} from "@/app/timezone";
import { Help } from "./Help";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Field, FieldLabel } from "./ui/field";
export function TimezoneSettings() {
  const preference = useTimezone();
  const [custom, setCustom] = useState("");
  const [error, setError] = useState("");
  function choose(value: string) {
    try {
      setTimezone(value);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <Help label={`显示时区 ${timezone()}`}>
      <div className="flex flex-col gap-3">
        <p>
          时间显示与维护时间输入使用 {timezone()}
          。偏好仅保存于此浏览器，不跨设备同步。
        </p>
        <Field>
          <FieldLabel htmlFor="timezone-preset">显示时区</FieldLabel>
          <select
            id="timezone-preset"
            value={preference}
            onChange={(e) => choose(e.target.value)}
          >
            <option value="browser">跟随浏览器（{browserZone}）</option>
            <option value="UTC">UTC</option>
            <option value="Asia/Shanghai">Asia/Shanghai</option>
            <option value="America/New_York">America/New_York</option>
            {!["browser", "UTC", "Asia/Shanghai", "America/New_York"].includes(
              preference,
            ) && <option value={preference}>{preference}</option>}
          </select>
        </Field>
        <Field>
          <FieldLabel htmlFor="timezone-custom">其它 IANA 命名时区</FieldLabel>
          <Input
            id="timezone-custom"
            value={custom}
            placeholder="Europe/London"
            onChange={(e) => setCustom(e.target.value)}
          />
        </Field>
        <Button onClick={() => choose(custom)}>应用时区</Button>
        {error && <p role="alert">{error}</p>}
      </div>
    </Help>
  );
}
