import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { WizardService } from '../../services/wizard.service';
import {
  AIReview,
  BidItem,
  Player,
  Position,
  ProtectionItem,
  SaleItem,
  WizardInitResponse,
} from '../../models';

/** Rotating loading messages while the backend crunches the data. */
const LOADING_MEMES = [
  'Llamando a Laporta para activar palancas...',
  'Sobornando al VAR...',
  'Preguntando a Ancelotti si va a rotar...',
  'Revisando si Lamine Yamal ha hecho los deberes...',
  'Consultando al oráculo de la IA...',
  'Calculando clausulazos traicioneros...',
  'Escondiendo la tarjeta de crédito...',
];

/** Only the strongest suggestions go through the (slow) news precheck. */
const PRECHECK_LIMIT = 12;

@Component({
  selector: 'app-wizard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './wizard.component.html',
  styleUrl: './wizard.component.css',
})
export class WizardComponent {
  readonly stepLabels = ['Datos', 'Mercado', 'Once', 'Ventas', 'Revisión IA'];

  step = 1;
  loading = false;
  executing = false;
  executionMessage = '';

  data: WizardInitResponse | null = null;
  bids: BidItem[] = [];
  sales: SaleItem[] = [];
  protections: ProtectionItem[] = [];
  projectedBalance = 0;

  aiLoading = false;
  aiReview: AIReview | null = null;
  aiStreamText = '';
  currentMeme = '';

  constructor(private wizardService: WizardService) {}

  // ------------------------------------------------------------------
  // Step 1: load everything and run the batched AI precheck
  // ------------------------------------------------------------------

  async initWizard(): Promise<void> {
    this.loading = true;

    let memeIndex = 0;
    this.currentMeme = LOADING_MEMES[memeIndex];
    const memeInterval = setInterval(() => {
      memeIndex = (memeIndex + 1) % LOADING_MEMES.length;
      this.currentMeme = LOADING_MEMES[memeIndex];
    }, 2500);

    try {
      const res = await this.wizardService.initWizard();
      this.data = res;
      this.bids = (res.market_suggestions || []).map((s) => ({ ...s, selected: true }));
      this.sales = res.sales || [];
      this.protections = res.protections || [];

      await this.runAIPrecheck();

      this.recalculateBalance();
      this.step = 2;
    } catch (err) {
      console.error(err);
      this.executionMessage = 'Error cargando datos del backend. ¿Está corriendo en el puerto 8000?';
    } finally {
      clearInterval(memeInterval);
      this.loading = false;
    }
  }

  /** One backend call checks injury news for the whole top of the market. */
  private async runAIPrecheck(): Promise<void> {
    const names = this.bids.slice(0, PRECHECK_LIMIT).map((b) => b.player_name);
    if (!names.length) return;

    this.currentMeme = `Pasando revisión médica con la IA a ${names.length} jugadores...`;
    try {
      const res = await this.wizardService.precheckPlayers(names);
      for (const bid of this.bids) {
        const verdict = res.verdicts[bid.player_name];
        if (verdict && !verdict.safe) {
          bid.selected = false;
          bid.ai_discard_reason = verdict.reason;
        }
      }
    } catch (e) {
      // A failed precheck shouldn't block the wizard: the user reviews bids anyway.
      console.error('AI precheck failed', e);
    }
  }

  // ------------------------------------------------------------------
  // Balance projection
  // ------------------------------------------------------------------

  adjustBid(bid: BidItem, amount: number): void {
    bid.suggested_bid = Math.max(0, bid.suggested_bid + amount);
    this.recalculateBalance();
  }

  recalculateBalance(): void {
    if (!this.data) return;
    this.projectedBalance = this.computeBalance();

    // Drop the worst-scored bids until the projection is solvent again.
    while (this.projectedBalance < 0) {
      const active = this.bids.filter((b) => b.selected).sort((a, b) => a.score - b.score);
      if (!active.length) break;
      active[0].selected = false;
      this.projectedBalance = this.computeBalance();
    }
  }

  private computeBalance(): number {
    const salesIncome = this.sales.reduce((sum, s) => sum + s.value, 0);
    const bidsSpend = this.bids
      .filter((b) => b.selected)
      .reduce((sum, b) => sum + b.suggested_bid, 0);
    return this.data!.finances.balance + salesIncome - bidsSpend;
  }

  get activeBids(): BidItem[] {
    return this.bids.filter((b) => b.selected);
  }

  get totalSpend(): number {
    return this.activeBids.reduce((sum, b) => sum + b.suggested_bid, 0);
  }

  get totalSalesIncome(): number {
    return this.sales.reduce((sum, s) => sum + s.value, 0);
  }

  get stepperProgress(): number {
    return ((Math.min(this.step, 5) - 1) / (this.stepLabels.length - 1)) * 100;
  }

  // ------------------------------------------------------------------
  // Lineup view
  // ------------------------------------------------------------------

  get lineupFormation(): string {
    return this.data?.lineup?.formation || 'Desconocida';
  }

  getLineupPlayersByPos(pos: Position): Player[] {
    if (!this.data) return [];

    const captainSlot = this.data.lineup.captain_slot;
    const slotByPlayer = new Map<number, number>();
    for (const [slot, id] of Object.entries(this.data.lineup.slots)) {
      slotByPlayer.set(id, Number(slot));
    }

    return this.data.squad.filter((p) => {
      const slot = slotByPlayer.get(p.id);
      if (slot === undefined || p.position !== pos) return false;
      p.isCaptain = slot === captainSlot;
      return true;
    });
  }

  initials(name: string): string {
    return name
      .split(' ')
      .map((part) => part[0])
      .join('')
      .slice(0, 2)
      .toUpperCase();
  }

  // ------------------------------------------------------------------
  // Step 5: AI review (SSE stream) and execution
  // ------------------------------------------------------------------

  getCartSummary(): string {
    let summary = `RESUMEN DE OPERACIONES\n`;
    summary += `----------------------\n`;
    summary += `Saldo Inicial: ${this.data?.finances?.balance}€\n`;
    summary += `Saldo Final Proyectado: ${this.projectedBalance}€\n\n`;

    summary += `COMPRAS (${this.activeBids.length}):\n`;
    this.activeBids.forEach((b) => {
      summary += `- ${b.player_name} (${b.type}): Pujar ${b.suggested_bid}€\n`;
    });

    summary += `\nALINEACIÓN:\nFormación: ${this.lineupFormation}\n`;

    summary += `\nVENTAS (${this.sales.length}):\n`;
    this.sales.forEach((s) => (summary += `- ${s.player_name}\n`));

    summary += `\nPROTECCIONES (${this.protections.length}):\n`;
    this.protections.forEach((p) => (summary += `- ${p.player_name}\n`));

    summary += `\nCONTEXTO PARA LA IA:\n--- TU PLANTILLA ACTUAL ---\n`;
    (this.data?.squad || []).forEach((p) => {
      summary += `- ${p.name} (${p.position}) | Pts: ${p.points} | Valor: ${p.value}€\n`;
    });

    summary += `\n--- JUGADORES DESTACADOS DE RIVALES ---\n`;
    const rivals = this.data?.rival_players || [];
    if (rivals.length) {
      // Only the most valuable rivals, to keep the prompt small.
      [...rivals]
        .sort((a, b) => (b.value || 0) - (a.value || 0))
        .slice(0, 15)
        .forEach((p) => {
          summary += `- ${p.name} (${p.position}) | Pts: ${p.points} | Valor: ${p.value}€\n`;
        });
    } else {
      summary += `No hay datos de rivales cargados o no son relevantes.\n`;
    }

    return summary;
  }

  async askAIReview(): Promise<void> {
    this.aiLoading = true;
    this.aiReview = null;
    this.aiStreamText = '';

    try {
      const response = await fetch(this.wizardService.getAiReviewStreamUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cart_summary: this.getCartSummary() }),
      });

      if (!response.ok || !response.body) {
        throw new Error('No se pudo conectar con el servidor.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      // SSE lines can be split across chunks, so keep a rolling buffer.
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const event = JSON.parse(line.substring(6));

          if (event.token) {
            this.aiStreamText += event.token;
          }
          if (event.done) {
            this.aiReview = { status: event.status, reason: event.reason };
            this.aiLoading = false;
            return;
          }
        }
      }

      if (!this.aiReview) {
        this.aiReview = { status: 'ERROR', reason: 'La conexión con la IA se cortó inesperadamente.' };
      }
    } catch (err) {
      console.error(err);
      this.aiReview = { status: 'ERROR', reason: 'Fallo de conexión con la IA.' };
    }
    this.aiLoading = false;
  }

  executeAll(): void {
    if (!this.data || this.projectedBalance < 0) return;

    this.executing = true;
    this.executionMessage = '';

    this.wizardService
      .executeAll({
        bids: this.activeBids,
        sales: this.sales,
        protections: this.protections,
        lineup: this.data.lineup,
      })
      .then((res) => {
        this.executing = false;
        if (res.success) {
          this.step = 6; // Success screen
        } else {
          this.executionMessage = res.message;
        }
      })
      .catch((err) => {
        console.error(err);
        this.executionMessage = 'Error de red al ejecutar el plan.';
        this.executing = false;
      });
  }

  restart(): void {
    this.step = 1;
    this.data = null;
    this.bids = [];
    this.sales = [];
    this.protections = [];
    this.aiReview = null;
    this.aiStreamText = '';
    this.executionMessage = '';
  }

  nextStep(): void {
    if (this.step < 5) this.step++;
  }

  prevStep(): void {
    if (this.step > 1) this.step--;
  }
}
