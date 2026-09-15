const GUIDE_EVENT = "deltadore_tydom_association_guide";
const DIALOG_TAG = "deltadore-association-guide-dialog";

class DeltaDoreAssociationGuideDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._close = this._close.bind(this);
  }

  connectedCallback() {
    this._render();
  }

  showGuide({
    title,
    instructions,
    overview,
    illustrations,
    illustration_mode: illustrationMode,
    illustration_step_indexes: illustrationStepIndexes,
    start_association_entity_id: startAssociationEntityId,
  }) {
    this._title = title;
    this._instructions = instructions;
    this._overview = overview;
    this._illustrations = illustrations;
    this._illustrationMode = illustrationMode;
    this._illustrationStepIndexes = illustrationStepIndexes;
    this._startAssociationEntityId = startAssociationEntityId;
    this._render();
    this.shadowRoot.querySelector(".backdrop")?.classList.add("visible");
    this.shadowRoot.querySelector(".dialog")?.focus();
  }

  _close() {
    this.shadowRoot.querySelector(".backdrop")?.classList.remove("visible");
  }

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    this.shadowRoot.innerHTML = `
      <style>
        :host { font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        .backdrop {
          align-items: center; background: rgba(0, 0, 0, .55); display: none;
          inset: 0; justify-content: center; padding: 16px; position: fixed;
          z-index: 10000;
        }
        .backdrop.visible { display: flex; }
        .dialog {
          background: var(--card-background-color, #fff); border-radius: 16px;
          box-shadow: 0 12px 36px rgba(0, 0, 0, .35); color: var(--primary-text-color, #212121);
          max-height: calc(100vh - 32px); max-width: 760px; outline: none; overflow: auto;
          width: 100%;
        }
        header {
          align-items: center; border-bottom: 1px solid var(--divider-color, #ddd);
          display: flex; gap: 12px; justify-content: space-between; padding: 20px 24px;
        }
        h2 { font-size: 22px; line-height: 1.25; margin: 0; }
        button {
          background: transparent; border: 0; border-radius: 50%; color: inherit;
          cursor: pointer; font-size: 28px; height: 40px; line-height: 1; width: 40px;
        }
        button:hover { background: var(--secondary-background-color, #eee); }
        main { padding: 20px 24px 28px; }
        ol { margin: 0; padding-left: 24px; }
        li { line-height: 1.45; margin: 0 0 14px; white-space: pre-line; }
        .lead { line-height: 1.45; margin: 0 0 18px; }
        h3 { font-size: 18px; margin: 28px 0 14px; }
        figure { margin: 0 0 20px; text-align: center; }
        .overview { border-bottom: 1px solid var(--divider-color, #ddd); margin: 0 0 20px; padding-bottom: 16px; }
        .step-illustration { margin: 12px 0 0; }
        img {
          background: #344457; border-radius: 12px; box-sizing: border-box; display: block;
          height: auto; margin: 0 auto; max-height: min(52vh, 480px); max-width: 100%;
          padding: 20px;
        }
        figcaption { color: var(--secondary-text-color, #666); font-size: 13px; margin-top: 6px; }
        .start-association {
          background: var(--primary-color, #03a9f4); border-radius: 8px; color: var(--text-primary-color, #fff);
          font-size: 15px; font-weight: 600; height: auto; line-height: 1.25; margin: 14px 0 0;
          padding: 11px 16px; width: auto;
        }
        .start-association:hover { background: var(--primary-color, #03a9f4); filter: brightness(.92); }
        .start-association:disabled { cursor: default; opacity: .7; }
        .action-status { color: var(--secondary-text-color, #666); display: block; font-size: 13px; margin-top: 8px; }
      </style>
      <div class="backdrop" role="presentation">
        <section class="dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title" tabindex="-1">
          <header>
            <h2 id="guide-title"></h2>
            <button type="button" aria-label="Fermer">×</button>
          </header>
          <main>
            <figure class="overview" hidden>
              <img alt="Illustration officielle du produit">
              <figcaption>Illustration officielle du produit</figcaption>
            </figure>
            <ol class="instructions"></ol>
            <section class="illustrations" hidden>
              <h3></h3>
              <div class="images"></div>
            </section>
          </main>
        </section>
      </div>
    `;

    const backdrop = this.shadowRoot.querySelector(".backdrop");
    const dialog = this.shadowRoot.querySelector(".dialog");
    const closeButton = this.shadowRoot.querySelector("button");
    closeButton.addEventListener("click", this._close);
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this._close();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this._close();
    });

    this.shadowRoot.querySelector("#guide-title").textContent = this._title || "Guide d'association";
    const overview = this.shadowRoot.querySelector(".overview");
    if (this._overview) {
      overview.querySelector("img").src = this._overview;
      overview.hidden = false;
    }
    const instructionList = this.shadowRoot.querySelector(".instructions");
    const instructions = [...(this._instructions || [])];
    if (/^Parcours Home Assistant\s*[—-]/.test(instructions[0] || "")) {
      const lead = document.createElement("p");
      lead.className = "lead";
      lead.textContent = instructions.shift();
      instructionList.before(lead);
    }
    instructions.forEach((instruction, index) => {
      const item = document.createElement("li");
      item.textContent = instruction.replace(/^\d+\.\s*/, "");
      const illustrationIndexes = (this._illustrationStepIndexes || [])
        .map((stepIndex, illustrationIndex) => ({ stepIndex, illustrationIndex }))
        .filter(({ stepIndex }) => stepIndex === index)
        .map(({ illustrationIndex }) => illustrationIndex);
      illustrationIndexes.forEach((illustrationIndex) => {
        if (!this._illustrations?.[illustrationIndex]) return;
        const figure = document.createElement("figure");
        figure.className = "step-illustration";
        const image = document.createElement("img");
        image.src = this._illustrations[illustrationIndex];
        image.alt = `Illustration officielle de l'étape ${index + 1}`;
        const caption = document.createElement("figcaption");
        caption.textContent = `Illustration de l'étape ${index + 1}`;
        figure.append(image, caption);
        item.append(figure);
      });
      if (
        this._startAssociationEntityId
        && instruction.includes("Lancer l'écoute de la passerelle")
      ) {
        const startButton = document.createElement("button");
        startButton.className = "start-association";
        startButton.type = "button";
        startButton.textContent = "Lancer l'écoute de la passerelle";
        const status = document.createElement("span");
        status.className = "action-status";
        startButton.addEventListener("click", async () => {
          const hass = document.querySelector("home-assistant")?.hass;
          if (!hass?.callService) return;
          startButton.disabled = true;
          status.textContent = "Écoute de la passerelle en cours…";
          try {
            await hass.callService("button", "press", {
              entity_id: this._startAssociationEntityId,
            });
            startButton.textContent = "Écoute de la passerelle démarrée";
            status.textContent = "Passez maintenant à l'étape suivante.";
          } catch (error) {
            startButton.disabled = false;
            status.textContent = "Impossible de lancer l'écoute. Réessayez.";
          }
        });
        item.append(startButton, status);
      }
      instructionList.append(item);
    });

    const remainingIllustrations = (this._illustrations || []).filter(
      (_source, index) => !(this._illustrationStepIndexes || []).includes(index),
    );
    if (remainingIllustrations.length) {
      const section = this.shadowRoot.querySelector(".illustrations");
      const sectionTitle = section.querySelector("h3");
      const images = this.shadowRoot.querySelector(".images");
      sectionTitle.textContent = "Illustrations officielles complémentaires";
      section.hidden = false;
      remainingIllustrations.forEach((source, index) => {
        const figure = document.createElement("figure");
        const image = document.createElement("img");
        image.src = source;
        const stepNumber = instructions.length + index + 1;
        image.alt = `Illustration officielle de l'étape ${stepNumber}`;
        const caption = document.createElement("figcaption");
        caption.textContent = `Étape ${stepNumber}`;
        figure.append(image, caption);
        images.append(figure);
      });
    }
  }
}

const getDialog = () => {
  let dialog = document.querySelector(DIALOG_TAG);
  if (!dialog) {
    dialog = document.createElement(DIALOG_TAG);
    document.body.append(dialog);
  }
  return dialog;
};

const subscribe = async () => {
  const hass = document.querySelector("home-assistant")?.hass;
  if (!hass?.connection) {
    window.setTimeout(subscribe, 500);
    return;
  }
  await hass.connection.subscribeEvents(
    (event) => getDialog().showGuide(event.data),
    GUIDE_EVENT,
  );
};

if (!customElements.get(DIALOG_TAG)) {
  customElements.define(DIALOG_TAG, DeltaDoreAssociationGuideDialog);
  subscribe();
}
