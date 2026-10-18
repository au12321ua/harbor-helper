import { useTheme } from "@/app/theme";
import { Toaster } from "sonner";

export function ThemeToaster() {
  const theme = useTheme();
  return <Toaster theme={theme} position="bottom-right" richColors />;
}
