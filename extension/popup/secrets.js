/* Popup API key 的本地混淆存储与草稿迁移。 */

(function attachPopupSecrets(globalScope) {
  const root = globalScope.BookmarkAdvisor || (globalScope.BookmarkAdvisor = {});
  const popup = root.Popup || (root.Popup = {});

  if (!root.Protocol && typeof require === "function") {
    require("../shared/message_protocol.js");
  }

  const DEFAULT_PURPOSE = "bookmark-advisor-api-key-v2";
  const NO_KEY_MESSAGE = "No usable obfuscated API key found. Paste one in Settings.";
  const OLD_KEY_MESSAGE = "Older passphrase-protected key found. Paste the key and save again to migrate.";

  function create(dependencies) {
    const options = dependencies || {};
    const chromeApi = options.chrome || globalScope.chrome;
    const cryptoApi = options.crypto || globalScope.crypto;
    const protocol = options.protocol || root.Protocol;

    if (!chromeApi || !chromeApi.runtime || !chromeApi.storage || !chromeApi.storage.local) {
      throw new Error("Popup Secrets requires chrome.runtime and chrome.storage.local.");
    }
    if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function" || !cryptoApi.subtle) {
      throw new Error("Popup Secrets requires Web Crypto.");
    }
    if (!protocol || !protocol.STORAGE_KEYS) {
      throw new Error("Popup Secrets requires the shared message protocol.");
    }
    if (typeof globalScope.btoa !== "function" || typeof globalScope.atob !== "function") {
      throw new Error("Popup Secrets requires base64 browser helpers.");
    }

    const activeKeyStorageName = protocol.STORAGE_KEYS.ENCRYPTED_API_KEY;
    const draftStorageName = protocol.STORAGE_KEYS.ENCRYPTED_API_KEY_DRAFT;
    const purpose = String(options.purpose || DEFAULT_PURPOSE);
    const runtimeId = String(
      (options.runtimeId !== undefined ? options.runtimeId : chromeApi.runtime.id) ||
      "unpacked-extension",
    );

    async function saveActiveKey(value) {
      await saveSecret(activeKeyStorageName, value);
    }

    function loadActiveKey() {
      return loadSecret(activeKeyStorageName);
    }

    async function saveDraft(value) {
      const area = draftStorageArea();
      await saveSecret(draftStorageName, value, area);
      if (area !== chromeApi.storage.local) {
        await removeFromArea(chromeApi.storage.local, draftStorageName);
      }
    }

    async function loadDraft() {
      try {
        return await loadSecret(draftStorageName, draftStorageArea());
      } catch (sessionError) {
        try {
          const legacyDraft = await loadSecret(
            draftStorageName,
            chromeApi.storage.local,
          );
          await removeFromArea(chromeApi.storage.local, draftStorageName);
          await saveDraft(legacyDraft);
          return legacyDraft;
        } catch (_legacyError) {
          throw sessionError;
        }
      }
    }

    async function clearDraft() {
      await Promise.all([
        removeFromArea(chromeApi.storage.local, draftStorageName).catch(() => {}),
        removeFromArea(draftStorageArea(), draftStorageName).catch(() => {}),
      ]);
    }

    function draftStorageArea() {
      return chromeApi.storage.session || chromeApi.storage.local;
    }

    async function saveSecret(storageName, value, area) {
      const targetArea = area || chromeApi.storage.local;
      const salt = cryptoApi.getRandomValues(new Uint8Array(16));
      const iv = cryptoApi.getRandomValues(new Uint8Array(12));
      const key = await deriveAutomaticStorageKey(salt);
      const ciphertext = await cryptoApi.subtle.encrypt(
        { name: "AES-GCM", iv },
        key,
        new TextEncoder().encode(value),
      );
      await setInArea(targetArea, storageName, {
        version: 2,
        kdf: "SHA-256(runtime-id)",
        cipher: "AES-GCM",
        salt: bytesToBase64(salt),
        iv: bytesToBase64(iv),
        ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
        created_at: new Date().toISOString(),
      });
    }

    async function loadSecret(storageName, area) {
      const targetArea = area || chromeApi.storage.local;
      const record = await getFromArea(targetArea, storageName);
      if (!record) {
        throw new Error(NO_KEY_MESSAGE);
      }
      if (record.version !== 2) {
        throw new Error(OLD_KEY_MESSAGE);
      }
      const salt = base64ToBytes(record.salt);
      const iv = base64ToBytes(record.iv);
      const ciphertext = base64ToBytes(record.ciphertext);
      const key = await deriveAutomaticStorageKey(salt);
      const plaintext = await cryptoApi.subtle.decrypt(
        { name: "AES-GCM", iv },
        key,
        ciphertext,
      );
      return new TextDecoder().decode(plaintext);
    }

    async function deriveAutomaticStorageKey(salt) {
      const material = [
        purpose,
        runtimeId,
        bytesToBase64(salt),
      ].join("\n");
      const digest = await cryptoApi.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(material),
      );
      return cryptoApi.subtle.importKey(
        "raw",
        digest,
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt", "decrypt"],
      );
    }

    function getFromArea(area, key) {
      return new Promise((resolve, reject) => {
        area.get(key, (result) => {
          if (chromeApi.runtime.lastError) {
            reject(new Error(chromeApi.runtime.lastError.message));
            return;
          }
          resolve(result[key]);
        });
      });
    }

    function setInArea(area, key, value) {
      return new Promise((resolve, reject) => {
        area.set({ [key]: value }, () => {
          if (chromeApi.runtime.lastError) {
            reject(new Error(chromeApi.runtime.lastError.message));
            return;
          }
          resolve();
        });
      });
    }

    function removeFromArea(area, key) {
      return new Promise((resolve, reject) => {
        area.remove(key, () => {
          if (chromeApi.runtime.lastError) {
            reject(new Error(chromeApi.runtime.lastError.message));
            return;
          }
          resolve();
        });
      });
    }

    function bytesToBase64(bytes) {
      let binary = "";
      for (const byte of bytes) {
        binary += String.fromCharCode(byte);
      }
      return globalScope.btoa(binary);
    }

    function base64ToBytes(value) {
      const binary = globalScope.atob(String(value || ""));
      return Uint8Array.from(binary, (character) => character.charCodeAt(0));
    }

    return Object.freeze({
      base64ToBytes,
      bytesToBase64,
      clearDraft,
      deriveAutomaticStorageKey,
      draftStorageArea,
      getFromArea,
      loadActiveKey,
      loadDraft,
      loadSecret,
      removeFromArea,
      saveActiveKey,
      saveDraft,
      saveSecret,
      setInArea,
    });
  }

  popup.Secrets = Object.freeze({
    create,
    DEFAULT_PURPOSE,
    NO_KEY_MESSAGE,
    OLD_KEY_MESSAGE,
  });
})(globalThis);
