// Concise get element by ID and assume it exists.
export function d(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement;
}

export function exists(id: string): boolean {
  return document.getElementById(id) != null;
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

// Fetch a URL
export function fetch(url: string, method: string = 'GET'): Promise<string> {
  return new Promise((resolve, reject) => {
    const http = new XMLHttpRequest();
    http.onload = () => {
      const status = http.status;
      if (status >= 200 && status < 300) {
        resolve(http.responseText);
      } else {
        reject(`${status}: ${http.responseText}`);
      }
    };
    http.open(method, url);
    http.send();
  });
}

// Show/hide elements.
export function show(elem: HTMLElement) {
  elem.classList.remove('_cls-hide');
}
export function hide(elem: HTMLElement) {
  elem.classList.add('_cls-hide');
}
