export function d(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement;
}

// Set event listener
export function on(
  element: HTMLElement,
  event: keyof HTMLElementEventMap | (keyof HTMLElementEventMap)[],
  fn: (e: Event) => void
) {
  if (Array.isArray(event)) {
    event.forEach(evt => element.addEventListener(evt, fn, false));
  } else {
    element.addEventListener(event, fn, false);
  }
}
