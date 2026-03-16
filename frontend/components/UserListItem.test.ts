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
          uuid: "abc-123",
          username: "janedoe",
          name: "Jane Doe",
          avatar_url: "/avatars/jane.png",
        },
      },
    });

    expect(target.textContent).toContain("Jane Doe");
    expect(target.textContent).toContain("janedoe");
  });

  it("falls back to username when name is empty", () => {
    const target = document.createElement("div");
    mount(UserListItem, {
      target,
      props: {
        user: {
          id: 2,
          uuid: "def-456",
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
          uuid: "ghi-789",
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
