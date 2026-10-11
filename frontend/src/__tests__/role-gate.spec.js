import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import RoleGate from "../auth/RoleGate.vue";
import { useAuthStore } from "../stores/auth.js";

/**
 * Mount the gate with the given role and an admin-only allow list.
 * @param {string|null} role session role (null = signed out)
 * @returns {object} mounted wrapper
 */
function mountGate(role) {
  setActivePinia(createPinia());
  const auth = useAuthStore();
  if (role !== null) {
    auth.user = { user_id: 1, username: "u", role, site_id: 1 };
  }
  return mount(RoleGate, {
    props: { roles: ["admin"] },
    slots: { default: "<span>admin-only content</span>" },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("RoleGate", () => {
  it("hides admin-only content from viewers (nav item absent)", () => {
    const wrapper = mountGate("viewer");
    expect(wrapper.find("span").exists()).toBe(false);
  });

  it("hides admin-only content when signed out", () => {
    const wrapper = mountGate(null);
    expect(wrapper.find("span").exists()).toBe(false);
  });

  it("shows admin-only content to admins", () => {
    const wrapper = mountGate("admin");
    expect(wrapper.find("span").text()).toBe("admin-only content");
  });
});
