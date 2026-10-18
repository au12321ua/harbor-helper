import * as Popover from "@radix-ui/react-popover";
import { CircleHelp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

export function Help({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pinned = useRef(false),
    timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  function enter() {
    clearTimeout(timer.current);
    setOpen(true);
  }
  function leave() {
    timer.current = setTimeout(() => {
      if (!pinned.current) setOpen(false);
    }, 150);
  }
  return (
    <Popover.Root
      open={open}
      onOpenChange={(value) => {
        pinned.current = value;
        setOpen(value);
      }}
    >
      <Popover.Trigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="help-trigger"
          aria-label={`${label}帮助`}
          onPointerEnter={(e) => {
            if (e.pointerType === "mouse") enter();
          }}
          onPointerLeave={leave}
          onFocus={enter}
          onBlur={leave}
          onClick={(e) => {
            e.preventDefault();
            clearTimeout(timer.current);
            if (pinned.current) {
              pinned.current = false;
              setOpen(false);
            } else {
              pinned.current = true;
              setOpen(true);
            }
          }}
        >
          <CircleHelp aria-hidden="true" />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="help-content"
          sideOffset={6}
          collisionPadding={12}
          onPointerEnter={enter}
          onPointerLeave={leave}
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onEscapeKeyDown={() => {
            pinned.current = false;
          }}
          onInteractOutside={() => {
            pinned.current = false;
          }}
          aria-label={label}
        >
          {children}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
