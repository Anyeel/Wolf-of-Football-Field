import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { WizardComponent } from './wizard.component';
import { WizardService } from '../../services/wizard.service';
import { BidItem, SaleItem, WizardInitResponse } from '../../models';

describe('WizardComponent', () => {
  let component: WizardComponent;
  let fixture: ComponentFixture<WizardComponent>;

  const makeData = (balance: number): WizardInitResponse => ({
    finances: { balance, max_bid: balance },
    market_suggestions: [],
    lineup: { formation: '4-4-2', score: 0, slots: {}, captain_slot: null },
    squad: [],
    sales: [],
    protections: [],
    rival_players: [],
  });

  const makeBid = (overrides: Partial<BidItem>): BidItem => ({
    type: 'free_agent',
    player_id: 1,
    player_name: 'Test Player',
    value: 100000,
    score: 0,
    suggested_bid: 0,
    reason: '',
    selected: true,
    ...overrides,
  });

  beforeEach(async () => {
    const spy = jasmine.createSpyObj('WizardService', [
      'initWizard',
      'precheckPlayers',
      'executeAll',
      'getAiReviewStreamUrl',
    ]);

    await TestBed.configureTestingModule({
      imports: [WizardComponent],
      providers: [provideHttpClient(), { provide: WizardService, useValue: spy }],
    }).compileComponents();

    fixture = TestBed.createComponent(WizardComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should calculate projected balance correctly', () => {
    component.data = makeData(1_000_000);
    component.sales = [
      { player_id: 1, player_name: 'A', value: 500_000, suggested_price: 500_000 } as SaleItem,
    ];
    component.bids = [
      makeBid({ suggested_bid: 200_000, selected: true }),
      makeBid({ suggested_bid: 100_000, selected: false }),
    ];

    component.recalculateBalance();

    // 1M (base) + 500k (sales) - 200k (selected bids) = 1.3M
    expect(component.projectedBalance).toEqual(1_300_000);
  });

  it('should auto drop worst bids until balance is solvent', () => {
    component.data = makeData(100_000);
    component.sales = [];
    component.bids = [
      makeBid({ suggested_bid: 200_000, selected: true, score: 50 }), // Best score
      makeBid({ suggested_bid: 150_000, selected: true, score: 20 }), // Worst score
    ];

    // 100k - 350k = -250k: the worst bid is dropped first, then the next one,
    // until the projection is solvent again (back to the base 100k).
    component.recalculateBalance();

    expect(component.bids[0].selected).toBeFalse();
    expect(component.bids[1].selected).toBeFalse();
    expect(component.projectedBalance).toEqual(100_000);
  });
});
