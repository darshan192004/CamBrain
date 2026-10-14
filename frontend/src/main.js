import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router.js";
import "./style.css";

// Pinia before the router: the first navigation awaits the auth store.
createApp(App).use(createPinia()).use(router).mount("#app");
