import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import App from "../App.vue";

describe("App scaffold", () => {
  it("mounts and renders the product title", () => {
    const wrapper = mount(App);
    expect(wrapper.find("h1").text()).toBe("CamBrain");
    wrapper.unmount();
  });
});
