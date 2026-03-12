/* for /organizations/<slug>/manage-members/ */
import type { Selection } from "../types";

import "@/css/sidebar_layout.css";
import "@/css/organization_managemembers.css";
import "@/css/user_list_item.css";
import "@/css/invitation_list_item.css";

import { mount } from "svelte";
import { showAlert } from "../alerts";
import UserSelect from "../components/UserSelect.svelte";

function main() {
  // Clipboard buttons for invite links
  document.querySelectorAll("button[data-clipboard]").forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      const target = e.currentTarget as HTMLButtonElement;
      window?.navigator?.clipboard?.writeText(target.value);
      showAlert("Invitation link copied to clipboard.", "success", {
        canDismiss: true,
        autoDismiss: true,
      });
    });
  });

  // Mount UserSelect onto the invite form
  const el = document.getElementById("user-select");
  if (!el) return; // no mount point — form works as plain HTML fallback

  const form = el.closest("form") as HTMLFormElement;
  const submitBtn = form.querySelector<HTMLButtonElement>(
    '[name="action"][value="addmember"]',
  );
  const orgId = form.dataset.orgId;

  // Hide the plain email fallback, show the Svelte widget
  form.querySelector(".email-fallback")?.setAttribute("hidden", "");

  let selections: Selection[] = [];
  let clearSelect: (() => void) | undefined;
  const state = $state({ disabled: false });

  mount(UserSelect, {
    target: el,
    props: {
      get disabled() {
        return state.disabled;
      },
      onChange(next: Selection[]) {
        selections = next;
        if (submitBtn) submitBtn.disabled = next.length === 0;
      },
      onReady(api: { clear: () => void }) {
        clearSelect = api.clear;
      },
    },
  });

  if (submitBtn) submitBtn.disabled = true;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (selections.length === 0) return;

    // Disable form while requests are in flight
    state.disabled = true;
    if (submitBtn) submitBtn.disabled = true;

    const role =
      form.querySelector<HTMLSelectElement>('[name="role"]')?.value ?? "0";
    const csrf =
      form.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')
        ?.value ?? "";

    const results = await Promise.allSettled(
      selections.map((sel) => {
        const body: Record<string, unknown> = {
          organization: orgId,
          role: parseInt(role),
          request: false,
        };
        if (sel.type === "email") {
          body.email = sel.email;
        } else {
          // Send user ID; backend resolves email in perform_create
          body.user = sel.id;
        }
        return fetch("/fe_api/invitations/", {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
          },
          body: JSON.stringify(body),
        }).then(async (r) => {
          const data = await r.json();
          if (!r.ok) throw r;
          return data as { status?: string };
        });
      }),
    );

    const alreadyMembers = results.filter(
      (r) => r.status === "fulfilled" && r.value.status === "already_member",
    ).length;
    const sent = results.filter(
      (r) => r.status === "fulfilled" && r.value.status !== "already_member",
    ).length;
    const failed = results.length - sent - alreadyMembers;
    if (sent > 0)
      showAlert(`${sent} invitation${sent !== 1 ? "s" : ""} sent.`, "success", {
        autoDismiss: true,
      });
    if (alreadyMembers > 0)
      showAlert(
        `${alreadyMembers} user${alreadyMembers !== 1 ? "s are" : " is"} already a member.`,
        "info",
        { autoDismiss: true },
      );
    if (failed > 0)
      showAlert(
        `${failed} invitation${failed !== 1 ? "s" : ""} failed to send.`,
        "error",
      );

    // Re-enable and clear on completion
    state.disabled = false;
    clearSelect?.();
    selections = [];
    if (submitBtn) submitBtn.disabled = true;
  });
}

window.addEventListener("DOMContentLoaded", main);
