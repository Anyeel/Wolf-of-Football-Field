import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  AIPrecheckResponse,
  ExecutePayload,
  ExecuteResponse,
  WizardInitResponse,
} from '../models';

@Injectable({
  providedIn: 'root',
})
export class WizardService {
  private readonly baseUrl = 'http://localhost:8000/api';

  constructor(private http: HttpClient) {}

  /** Downloads market, squad, rivals and the computed matchday plan. */
  initWizard(): Promise<WizardInitResponse> {
    return firstValueFrom(this.http.get<WizardInitResponse>(`${this.baseUrl}/wizard/init`));
  }

  /** Batched injury/rotation check: one backend call for the whole list. */
  precheckPlayers(players: string[]): Promise<AIPrecheckResponse> {
    return firstValueFrom(
      this.http.post<AIPrecheckResponse>(`${this.baseUrl}/wizard/ai-precheck`, { players })
    );
  }

  /** Executes the confirmed plan (bids, sales, protections, lineup) on Mister. */
  executeAll(payload: ExecutePayload): Promise<ExecuteResponse> {
    return firstValueFrom(
      this.http.post<ExecuteResponse>(`${this.baseUrl}/wizard/execute`, payload)
    );
  }

  /** SSE endpoint consumed with fetch() to stream the AI review token by token. */
  getAiReviewStreamUrl(): string {
    return `${this.baseUrl}/wizard/ai-review`;
  }
}
