import { describe, it, expect } from "vitest";
import { mount } from "svelte";
import UserListItem from "./UserListItem.svelte";

describe("UserListItem", () => {
  it("renders user name and username", () => {
    const target = document.createElement("div");
    mount(UserListItem, {
      target,
      props: {
        user: {
          id: 1,
          username: "janedoe",
          name: "Jane Doe",
          avatar_url: "/avatars/jane.png",
        },
      },
    });

    expect(target.textContent).toContain("Jane Doe");
    expect(target.textContent).toContain("janedoe");
    expect(target.textContent).not.toContain("@example.com");
  });

  it("falls back to username when name is empty", () => {
    const target = document.createElement("div");
    mount(UserListItem, {
      target,
      props: {
        user: {
          id: 2,
          username: "noname",
          name: "",
          avatar_url: "",
        },
      },
    });

    const nameEl = target.querySelector(".name");
    expect(nameEl?.textContent).toBe("noname");
  });

  it("renders the avatar image", () => {
    const target = document.createElement("div");
    mount(UserListItem, {
      target,
      props: {
        user: {
          id: 3,
          username: "avataruser",
          name: "Avatar User",
          avatar_url: "/avatars/avatar.png",
        },
      },
    });

    const img = target.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.src).toContain("/avatars/avatar.png");
  });
});
