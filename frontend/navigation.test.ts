import { beforeEach, describe, expect, it } from "vitest";
import { initNavigation } from "./navigation";

// document listeners accumulate across tests, so each test inits once on fresh markup
function render() {
  document.body.innerHTML = `
    <button class="_cls-navMenuButton"></button>
    <div class="_cls-navMenu"></div>
    <div class="_cls-servicesDropdown"><button class="_cls-servicesToggle"></button></div>
    <div class="_cls-orgsDropdown"><button class="_cls-orgsToggle"></button></div>`;
  initNavigation();
  return {
    menuButton: document.querySelector<HTMLElement>("._cls-navMenuButton")!,
    menu: document.querySelector<HTMLElement>("._cls-navMenu")!,
    services: document.querySelector<HTMLElement>("._cls-servicesDropdown")!,
    orgs: document.querySelector<HTMLElement>("._cls-orgsDropdown")!,
    servicesToggle: document.querySelector<HTMLElement>("._cls-servicesToggle")!,
    orgsToggle: document.querySelector<HTMLElement>("._cls-orgsToggle")!,
  };
}

describe("navigation", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("opens the mobile menu on the first click and closes it on the second", () => {
    const { menuButton, menu } = render();
    menuButton.click();
    expect(menu.dataset.menuOpen).toBe("true");
    expect(menuButton.dataset.menuOpen).toBe("true");
    menuButton.click();
    expect(menu.dataset.menuOpen).toBe("false");
  });

  it("opening the organizations dropdown closes the services dropdown", () => {
    const { services, orgs, servicesToggle, orgsToggle } = render();
    servicesToggle.click();
    expect(services.dataset.open).toBe("true");
    orgsToggle.click();
    expect(orgs.dataset.open).toBe("true");
    expect(services.dataset.open).toBe("false");
  });

  it("a click elsewhere on the page closes an open dropdown", () => {
    const { services, servicesToggle } = render();
    servicesToggle.click();
    document.body.click();
    expect(services.dataset.open).toBe("false");
  });

  it("clicking an open dropdown's toggle closes it", () => {
    const { orgs, orgsToggle } = render();
    orgsToggle.click();
    orgsToggle.click();
    expect(orgs.dataset.open).toBe("false");
  });

  it("does nothing on a page without the navigation markup", () => {
    document.body.innerHTML = "";
    expect(() => initNavigation()).not.toThrow();
  });
});
