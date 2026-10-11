/**
 * Camera list store (Pinia): the grid's data source. `load` replaces the
 * list from `GET /cameras`; `create` appends the 201 camera so a dialog
 * can close and the new tile appear without a refetch.
 * @module stores/cameras
 */

import { defineStore } from "pinia";

import { get, post } from "../api/client.js";

/**
 * @returns {object} Pinia store options for the camera list
 */
export const useCamerasStore = defineStore("cameras", {
  state: () => ({
    /** @type {object[]} CameraOut rows */
    cameras: [],
  }),

  actions: {
    /**
     * Replace the list from the API. A non-array body clears the grid
     * rather than crashing the v-for.
     * @returns {Promise<void>} resolves when the list is current
     */
    async load() {
      const rows = await get("/cameras");
      this.cameras = Array.isArray(rows) ? rows : [];
    },

    /**
     * Create a camera (admin) and append it to the grid.
     * @param {object} payload CameraCreate body
     * @returns {Promise<object>} the created CameraOut row
     */
    async create(payload) {
      const camera = await post("/cameras", payload);
      this.cameras.push(camera);
      return camera;
    },
  },
});
