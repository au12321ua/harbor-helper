import type { Page } from "@playwright/test";

// Sample actual rendered text against the entire background stack, including
// translucent hover/selection colors. Disabled controls are an explicit exception.
export async function contrastSamples(page: Page) {
  return page.evaluate(() => {
    type Color = [number, number, number, number];
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const parse = (value: string): Color => {
      // Chromium may return color(srgb), oklab or color-mix, not just rgb().
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (fg: Color, bg: Color): Color =>
      [
        ...fg.slice(0, 3).map((v, i) => v * fg[3] + bg[i] * (1 - fg[3])),
        1,
      ] as Color;
    const lum = (c: Color) =>
      c
        .slice(0, 3)
        .map((v) => {
          v /= 255;
          return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        })
        .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
    const hex = (c: Color) =>
      "#" +
      c
        .slice(0, 3)
        .map((v) => Math.round(v).toString(16).padStart(2, "0"))
        .join("");
    const samples = new Map<
      string,
      {
        usage: string;
        text: string;
        foreground: string;
        background: string;
        ratio: number;
        minimum: number;
      }
    >();
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      const rect = el.getBoundingClientRect(),
        style = getComputedStyle(el);
      if (
        rect.width < 1 ||
        rect.height < 1 ||
        style.visibility === "hidden" ||
        style.display === "none" ||
        el.closest(':disabled,[aria-disabled="true"],[inert]')
      )
        continue;
      let opacity = 1;
      const stack: Element[] = [];
      for (let p: Element | null = el; p; p = p.parentElement) {
        stack.unshift(p);
        opacity *= Number(getComputedStyle(p).opacity);
      }
      if (opacity < 0.99) continue; // hidden/animating or disabled ancestor; record stable states only
      let bg: Color = [255, 255, 255, 1];
      stack.forEach((p) => {
        bg = over(parse(getComputedStyle(p).backgroundColor), bg);
      });
      const text = [...el.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent?.trim())
        .filter(Boolean)
        .join(" ");
      if (!text && !el.matches('input:not([type="checkbox"]),textarea,select'))
        continue;
      const fg = over(parse(style.color), bg);
      const l1 = lum(fg),
        l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const usage =
        el.tagName.toLowerCase() +
        "." +
        el.className.toString().split(" ").slice(0, 2).join(".");
      const k = `${hex(fg)}/${hex(bg)}`;
      if (!samples.has(k))
        samples.set(k, {
          usage,
          text: (text || el.getAttribute("placeholder") || el.tagName).slice(
            0,
            90,
          ),
          foreground: hex(fg),
          background: hex(bg),
          ratio,
          minimum: 4.5,
        });
    }
    // Focus outline and selected navigation markers carry meaning beyond text.
    for (const selector of [
      ".theme-toggle:focus-visible",
      ".sidebar nav a.active",
    ]) {
      const el = document.querySelector<HTMLElement>(selector);
      if (!el || !el.getClientRects().length) continue;
      const style = getComputedStyle(el);
      const color = parse(
        selector.includes("focus") ? style.outlineColor : style.borderLeftColor,
      );
      let bg: Color = [255, 255, 255, 1];
      const stack: Element[] = [];
      for (let p: Element | null = el.parentElement; p; p = p.parentElement)
        stack.unshift(p);
      stack.forEach((p) => {
        bg = over(parse(getComputedStyle(p).backgroundColor), bg);
      });
      const fg = over(color, bg),
        a = lum(fg),
        b = lum(bg);
      samples.set(selector, {
        usage: selector,
        text: "focus / selected marker",
        foreground: hex(fg),
        background: hex(bg),
        ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
        minimum: 3,
      });
    }
    return [...samples.values()];
  });
}
