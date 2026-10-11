import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { describe, expect, it } from "vitest";

import App from "../App.vue";
import { createAppRouter } from "../router.js";

describe("App scaffold", () => {
  it("mounts and lands on the login card when signed out", async () => {
    const router = createAppRouter();
    const wrapper = mount(App, {
      global: { plugins: [createPinia(), router] },
    });
    // Vitest resolves vue-router's node build, which does not auto-start the
    // initial navigation the way the browser build does.
    await router.push("/");
    await flushPromises();
    expect(wrapper.find("h1").text()).toBe("CamBrain");
    wrapper.unmount();
  });
});
