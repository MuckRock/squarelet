import { d } from "./util";

export class Modal {
  private backdrop: HTMLElement;
  private modalId: string;

  constructor(modalId: string) {
    this.modalId = modalId;
    this.backdrop = d(`${modalId}-backdrop`);
    this.setupEventListeners();
  }

  private setupEventListeners(): void {
    // Close on backdrop click
    this.backdrop.addEventListener("click", (e) => {
      if (e.target === this.backdrop) {
        this.close();
      }
    });

    // Close on close button click
    const closeButtons = this.backdrop.querySelectorAll("[data-dismiss='modal']");
    closeButtons.forEach((button) => {
      button.addEventListener("click", () => this.close());
    });

    // Close on Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.backdrop.classList.contains("_cls-hide")) {
        this.close();
      }
    });
  }

  public open(): void {
    this.backdrop.classList.remove("_cls-hide");
    document.body.style.overflow = "hidden"; // Prevent background scroll
  }

  public close(): void {
    this.backdrop.classList.add("_cls-hide");
    document.body.style.overflow = ""; // Restore scroll
  }
}
