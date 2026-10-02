function setOpen(el: HTMLElement | null, open: boolean) {
  if (el) el.dataset.open = String(open);
}

export function initNavigation() {
  const menuButton = document.querySelector<HTMLElement>("._cls-navMenuButton");
  const menu = document.querySelector<HTMLElement>("._cls-navMenu");
  const servicesToggle = document.querySelector("._cls-servicesToggle");
  const servicesDropdown = document.querySelector<HTMLElement>("._cls-servicesDropdown");
  const orgsToggle = document.querySelector("._cls-orgsToggle");
  const orgsDropdown = document.querySelector<HTMLElement>("._cls-orgsDropdown");

  // Mobile menu
  let menuOpen = false;
  menuButton?.addEventListener("click", () => {
    menuOpen = !menuOpen;
    if (menuButton) menuButton.dataset.menuOpen = String(menuOpen);
    if (menu) menu.dataset.menuOpen = String(menuOpen);
  });

  // Each dropdown closes the other, and both close on any outside click.
  const dropdowns = [servicesDropdown, orgsDropdown];
  const closeAll = () => dropdowns.forEach((el) => setOpen(el, false));

  function bindDropdown(toggle: Element | null, dropdown: HTMLElement | null) {
    if (!toggle) return;
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = dropdown?.dataset.open !== "true";
      closeAll();
      setOpen(dropdown, open);
    });
  }

  bindDropdown(servicesToggle, servicesDropdown);
  bindDropdown(orgsToggle, orgsDropdown);
  if (servicesToggle || orgsToggle) document.addEventListener("click", closeAll);
}
