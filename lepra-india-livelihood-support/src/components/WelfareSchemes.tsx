import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Beneficiary, DiseaseType, TreatmentStatus, WelfareScheme } from '../types';
import {
  HandHeart, Plus, Trash2, Banknote, CalendarDays, Gift, Landmark, Search, UserPlus, X
} from 'lucide-react';
import { INDIAN_STATES_AND_UTS } from '../utils/normalizeState';

interface WelfareSchemesProps {
  beneficiaries: Beneficiary[];
  onAddBeneficiary: (beneficiary: Beneficiary) => void | Promise<any>;
  onUpdateBeneficiary: (updated: Beneficiary) => void | Promise<void>;
  loggedBy?: string;
}

const COMMON_SCHEMES = [
  'Disability Pension',
  'Old Age Pension (NSAP)',
  'Widow Pension',
  'MGNREGA',
  'Ayushman Bharat (PM-JAY)',
  'PM Awas Yojana (Housing)',
  'National Food Security (Ration)',
  'Disability Certificate (UDID)',
  'Swachh Bharat (Toilet)',
  'Ujjwala (LPG)',
  'Other'
];



const BENEFIT_TYPES = [
  'Monthly Pension',
  'One-time Grant',
  'Health Insurance Cover',
  'Housing Assistance',
  'Subsidised Ration',
  'Wage Employment',
  'Certificate / Entitlement',
  'In-kind Material',
  'Other'
];

export default function WelfareSchemes({ beneficiaries, onAddBeneficiary, onUpdateBeneficiary, loggedBy }: WelfareSchemesProps) {
  const { t } = useTranslation('welfareSchemes');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // Independent "Add Beneficiary" flow — lets a welfare-scheme-only beneficiary
  // (one who never goes through the livelihood Secure Intake Form) be captured
  // directly here, without a business plan or loan application.
  const [showAddBeneficiary, setShowAddBeneficiary] = useState(false);
  const [newBenType, setNewBenType] = useState<'Individual' | 'Group'>('Individual');
  const [newBenName, setNewBenName] = useState('');
  const [newBenContact, setNewBenContact] = useState('');
  const [newBenGender, setNewBenGender] = useState<'Male' | 'Female' | 'Other' | 'N/A'>('Male');
  const [newBenAge, setNewBenAge] = useState<number>(30);
  const [newBenAddress, setNewBenAddress] = useState('');
  const [newBenDistrict, setNewBenDistrict] = useState('');
  const [newBenState, setNewBenState] = useState('');
  const [newBenProjectName, setNewBenProjectName] = useState('Kind Cares Livelihood Support Project');
  const [newBenFundingPartner, setNewBenFundingPartner] = useState('Kind Cares');
  const [newBenDiseaseType, setNewBenDiseaseType] = useState<DiseaseType>('Leprosy');
  const [newBenDiagnosisYear, setNewBenDiagnosisYear] = useState<number>(2024);
  const [newBenTreatmentStatus, setNewBenTreatmentStatus] = useState<TreatmentStatus>('Completed');
  const [savingNewBeneficiary, setSavingNewBeneficiary] = useState(false);
  // Set right after a successful add so the beneficiary can be auto-selected once
  // it arrives back through the live `beneficiaries` subscription (it has no
  // client-side id yet — the backend assigns one on write). Contact number is
  // paired with the name so two beneficiaries sharing a common name don't get
  // conflated when we match on the way back in.
  const [awaitingNewBeneficiary, setAwaitingNewBeneficiary] = useState<{ name: string; contactNumber: string } | null>(null);

  // New scheme form
  const [schemeName, setSchemeName] = useState(COMMON_SCHEMES[0]);
  const [customSchemeName, setCustomSchemeName] = useState('');
  const [dateOfLinkage, setDateOfLinkage] = useState(new Date().toISOString().slice(0, 10));
  const [benefitType, setBenefitType] = useState(BENEFIT_TYPES[0]);
  const [monetaryValue, setMonetaryValue] = useState<number | ''>('');
  const [nonMonetarySupport, setNonMonetarySupport] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  // Transient confirmation shown after a scheme is saved, so it's visible at a
  // glance that the new linkage was added on top of — not in place of — the
  // beneficiary's previously recorded schemes.
  const [lastSavedCount, setLastSavedCount] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return beneficiaries;
    return beneficiaries.filter(b =>
      b.name.toLowerCase().includes(q) ||
      b.id.toLowerCase().includes(q) ||
      (b.businessName || '').toLowerCase().includes(q)
    );
  }, [beneficiaries, search]);

  const selected = beneficiaries.find(b => b.id === selectedId) || null;
  const schemes: WelfareScheme[] = Array.isArray(selected?.welfareSchemes) ? selected!.welfareSchemes : [];

  // Portfolio-wide convergence summary
  const totals = useMemo(() => {
    let linkedBeneficiaries = 0;
    let totalLinkages = 0;
    let totalMonetary = 0;
    beneficiaries.forEach(b => {
      const list = Array.isArray(b.welfareSchemes) ? b.welfareSchemes : [];
      if (list.length > 0) linkedBeneficiaries += 1;
      totalLinkages += list.length;
      totalMonetary += list.reduce((s, w) => s + (w.monetaryValue || 0), 0);
    });
    return { linkedBeneficiaries, totalLinkages, totalMonetary };
  }, [beneficiaries]);

  // Once the newly-added beneficiary comes back through the live subscription,
  // select it automatically so the agent can add a scheme linkage right away.
  useEffect(() => {
    if (!awaitingNewBeneficiary) return;
    const match = beneficiaries.find(b =>
      b.name === awaitingNewBeneficiary.name &&
      b.contactNumber === awaitingNewBeneficiary.contactNumber &&
      b.isWelfareOnly
    );
    if (match) {
      setSelectedId(match.id);
      setAwaitingNewBeneficiary(null);
    }
  }, [beneficiaries, awaitingNewBeneficiary]);

  const resetAddBeneficiaryForm = () => {
    setNewBenType('Individual');
    setNewBenName('');
    setNewBenContact('');
    setNewBenGender('Male');
    setNewBenAge(30);
    setNewBenAddress('');
    setNewBenDistrict('');
    setNewBenState('');
    setNewBenProjectName('Kind Cares Livelihood Support Project');
    setNewBenFundingPartner('Kind Cares');
    setNewBenDiseaseType('Leprosy');
    setNewBenDiagnosisYear(2024);
    setNewBenTreatmentStatus('Completed');
  };

  const handleAddBeneficiarySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBenName.trim() || !newBenContact.trim()) {
      alert(t('alertBeneficiaryMissingFields'));
      return;
    }

    const newBen: Beneficiary = {
      id: `BEN-${Math.floor(100 + Math.random() * 900)}`,
      type: newBenType,
      name: newBenName.trim(),
      contactNumber: newBenContact.trim(),
      gender: newBenGender,
      age: Number(newBenAge),
      address: newBenAddress.trim(),
      district: newBenDistrict.trim(),
      state: newBenState.trim(),
      projectName: newBenProjectName.trim() || undefined,
      fundingPartner: newBenFundingPartner.trim() || undefined,
      diseaseType: newBenDiseaseType,
      diagnosisYear: Number(newBenDiagnosisYear),
      treatmentStatus: newBenTreatmentStatus,
      physicalLimitations: [],
      // No livelihood/business application — this beneficiary only needs
      // welfare scheme linkages tracked, so the loan pipeline fields stay blank.
      businessName: '',
      businessSector: '',
      requestedAmount: 0,
      businessDescription: '',
      expectedMonthlyRevenue: 0,
      status: 'Verified Active',
      isWelfareOnly: true,
      registeredAt: new Date().toISOString(),
      registeredByAgent: loggedBy || 'Portal User',
      emiSchedule: [],
      payments: [],
      welfareSchemes: []
    };

    setSavingNewBeneficiary(true);
    try {
      await Promise.resolve(onAddBeneficiary(newBen));
      setAwaitingNewBeneficiary({ name: newBen.name, contactNumber: newBen.contactNumber });
      resetAddBeneficiaryForm();
      setShowAddBeneficiary(false);
    } catch (err) {
      console.error('Failed to add welfare-only beneficiary', err);
      alert(t('alertBeneficiarySaveFailed'));
    } finally {
      setSavingNewBeneficiary(false);
    }
  };

  // Dismiss the "linkage saved" confirmation automatically, and clear it
  // immediately if the agent switches to a different beneficiary.
  useEffect(() => {
    setLastSavedCount(null);
  }, [selectedId]);

  useEffect(() => {
    if (lastSavedCount === null) return;
    const timer = setTimeout(() => setLastSavedCount(null), 5000);
    return () => clearTimeout(timer);
  }, [lastSavedCount]);

  const resetForm = () => {
    setSchemeName(COMMON_SCHEMES[0]);
    setCustomSchemeName('');
    setDateOfLinkage(new Date().toISOString().slice(0, 10));
    setBenefitType(BENEFIT_TYPES[0]);
    setMonetaryValue('');
    setNonMonetarySupport('');
    setNotes('');
  };

  const handleAddScheme = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;

    const finalName = schemeName === 'Other' ? customSchemeName.trim() : schemeName;
    if (!finalName) {
      alert(t('alertEnterSchemeName'));
      return;
    }

    const newScheme: WelfareScheme = {
      id: `WS-${Date.now()}-${Math.floor(100 + Math.random() * 900)}`,
      schemeName: finalName,
      dateOfLinkage,
      benefitType,
      monetaryValue: monetaryValue === '' ? undefined : Number(monetaryValue),
      nonMonetarySupport: nonMonetarySupport.trim() || undefined,
      notes: notes.trim() || undefined,
      loggedBy: loggedBy || 'Portal User'
    };

    const existing = Array.isArray(selected.welfareSchemes) ? selected.welfareSchemes : [];
    const updatedSchemes = [...existing, newScheme];
    const updated: Beneficiary = { ...selected, welfareSchemes: updatedSchemes };

    setSaving(true);
    try {
      await onUpdateBeneficiary(updated);
      resetForm();
      // Confirms the linkage was appended alongside — not in place of — any
      // schemes already recorded for this beneficiary.
      setLastSavedCount(updatedSchemes.length);
    } catch (err) {
      console.error('Failed to save welfare scheme', err);
      alert(t('alertSaveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveScheme = async (schemeId: string) => {
    if (!selected) return;
    if (!confirm(t('confirmRemoveLinkage'))) return;
    const existing = Array.isArray(selected.welfareSchemes) ? selected.welfareSchemes : [];
    const updated: Beneficiary = { ...selected, welfareSchemes: existing.filter(s => s.id !== schemeId) };
    try {
      await onUpdateBeneficiary(updated);
    } catch (err) {
      console.error('Failed to remove welfare scheme', err);
      alert(t('alertRemoveFailed'));
    }
  };

  return (
    <div className="space-y-4" id="welfare_schemes_panel">
      {/* Header / convergence summary */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
        <div className="p-3 bg-[#115e59] text-white border-b-2 border-[#0284c7] flex items-center gap-2">
          <HandHeart className="w-4 h-4 text-[#0284c7]" />
          <h3 className="font-bold text-xs uppercase tracking-wider">{t('headerTitle')}</h3>
        </div>
        <div className="grid grid-cols-3 divide-x divide-gray-100 text-center">
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('beneficiariesLinked')}</span>
            <span className="font-bold text-[#115e59] text-lg font-mono">{totals.linkedBeneficiaries}</span>
          </div>
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('totalLinkages')}</span>
            <span className="font-bold text-indigo-700 text-lg font-mono">{totals.totalLinkages}</span>
          </div>
          <div className="p-3">
            <span className="block text-[11px] text-gray-400 uppercase font-bold tracking-wider">{t('monetaryValueTracked')}</span>
            <span className="font-bold text-emerald-700 text-lg font-mono">₹{totals.totalMonetary.toLocaleString('en-IN')}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Beneficiary selector */}
        <div className="lg:col-span-1 space-y-3 bg-slate-50 p-4 rounded-xl border border-gray-100">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-xs font-bold text-gray-700 uppercase tracking-wider">{t('selectBeneficiary')}</h4>
            <button
              type="button"
              onClick={() => setShowAddBeneficiary((v) => !v)}
              className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-white bg-[#115e59] hover:bg-[#0f766e] px-2 py-1 rounded-md cursor-pointer shrink-0"
            >
              {showAddBeneficiary ? <X className="w-3 h-3" /> : <UserPlus className="w-3 h-3" />}
              {showAddBeneficiary ? t('cancelAddBeneficiary') : t('addBeneficiaryButton')}
            </button>
          </div>
          <p className="text-[10px] text-gray-500 leading-relaxed">{t('independentEntryNotice')}</p>

          {showAddBeneficiary && (
            <form onSubmit={handleAddBeneficiarySubmit} className="bg-white border border-indigo-100 rounded-lg p-3 space-y-2.5 animate-fade-in">
              <span className="font-bold text-indigo-900 text-[10px] uppercase tracking-wider flex items-center gap-1.5">
                <UserPlus className="w-3 h-3" /> {t('addBeneficiaryFormTitle')}
              </span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setNewBenType('Individual')}
                  className={`py-1.5 px-2 text-[10px] font-bold rounded border text-center transition-all cursor-pointer ${
                    newBenType === 'Individual' ? 'bg-[#115e59] border-[#115e59] text-white' : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {t('typeIndividual')}
                </button>
                <button
                  type="button"
                  onClick={() => setNewBenType('Group')}
                  className={`py-1.5 px-2 text-[10px] font-bold rounded border text-center transition-all cursor-pointer ${
                    newBenType === 'Group' ? 'bg-[#115e59] border-[#115e59] text-white' : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {t('typeGroup')}
                </button>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('nameLabel')}</label>
                <input
                  type="text"
                  required
                  value={newBenName}
                  onChange={(e) => setNewBenName(e.target.value)}
                  placeholder={t('namePlaceholder')}
                  className="w-full text-xs border border-gray-200 p-2 rounded"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('contactLabel')}</label>
                  <input
                    type="tel"
                    required
                    pattern="[0-9]{10}"
                    value={newBenContact}
                    onChange={(e) => setNewBenContact(e.target.value)}
                    placeholder={t('contactPlaceholder')}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('ageLabel')}</label>
                  <input
                    type="number"
                    min={1}
                    max={110}
                    value={newBenAge}
                    onChange={(e) => setNewBenAge(Number(e.target.value))}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('genderLabel')}</label>
                <select
                  value={newBenGender}
                  onChange={(e) => setNewBenGender(e.target.value as any)}
                  className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                >
                  <option value="Male">{t('genderMale')}</option>
                  <option value="Female">{t('genderFemale')}</option>
                  <option value="Other">{t('genderOther')}</option>
                  <option value="N/A">{t('genderNA')}</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('districtLabel')}</label>
                  <input
                    type="text"
                    value={newBenDistrict}
                    onChange={(e) => setNewBenDistrict(e.target.value)}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('stateLabel')}</label>
                  <select
                    value={newBenState}
                    onChange={(e) => setNewBenState(e.target.value)}
                    className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                  >
                    <option value="">{t('stateLabel')}</option>
                    {INDIAN_STATES_AND_UTS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('addressLabel')}</label>
                <input
                  type="text"
                  value={newBenAddress}
                  onChange={(e) => setNewBenAddress(e.target.value)}
                  placeholder={t('addressPlaceholder')}
                  className="w-full text-xs border border-gray-200 p-2 rounded"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('projectNameLabel')}</label>
                  <input
                    type="text"
                    value={newBenProjectName}
                    onChange={(e) => setNewBenProjectName(e.target.value)}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('fundingPartnerLabel')}</label>
                  <input
                    type="text"
                    value={newBenFundingPartner}
                    onChange={(e) => setNewBenFundingPartner(e.target.value)}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('diseaseTypeLabel')}</label>
                  <select
                    value={newBenDiseaseType}
                    onChange={(e) => setNewBenDiseaseType(e.target.value as DiseaseType)}
                    className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                  >
                    <option value="Leprosy">{t('diseaseLeprosy')}</option>
                    <option value="Leptospirosis">{t('diseaseLeptospirosis')}</option>
                    <option value="LF">{t('diseaseLF')}</option>
                    <option value="HIV/AIDS">{t('diseaseHiv')}</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('diagnosisYearLabel')}</label>
                  <input
                    type="number"
                    min={2000}
                    max={2026}
                    value={newBenDiagnosisYear}
                    onChange={(e) => setNewBenDiagnosisYear(Number(e.target.value))}
                    className="w-full text-xs border border-gray-200 p-2 rounded"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase mb-1">{t('treatmentStatusLabel')}</label>
                  <select
                    value={newBenTreatmentStatus}
                    onChange={(e) => setNewBenTreatmentStatus(e.target.value as TreatmentStatus)}
                    className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                  >
                    <option value="Completed">{t('treatmentCompleted')}</option>
                    <option value="Under Treatment">{t('treatmentUnder')}</option>
                    <option value="Rehabilitation">{t('treatmentRehabilitation')}</option>
                  </select>
                </div>
              </div>
              <button
                type="submit"
                disabled={savingNewBeneficiary}
                className="w-full bg-[#115e59] hover:bg-[#0f766e] disabled:opacity-60 border-b-2 border-[#0284c7] text-white font-bold text-[10px] py-2 rounded cursor-pointer uppercase tracking-wider"
              >
                {savingNewBeneficiary ? t('saving') : t('saveBeneficiaryButton')}
              </button>
            </form>
          )}

          <div className="relative">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('searchPlaceholder')}
              className="w-full text-xs border border-gray-200 pl-8 pr-2 py-2 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-indigo-100 focus:border-indigo-500"
            />
          </div>
          <div className="space-y-2 max-h-[460px] overflow-y-auto">
            {filtered.length === 0 ? (
              <span className="text-gray-400 text-xs italic block p-4 text-center">{t('noBeneficiariesFound')}</span>
            ) : (
              filtered.map((b) => {
                const count = Array.isArray(b.welfareSchemes) ? b.welfareSchemes.length : 0;
                const isSelected = selectedId === b.id;
                return (
                  <button
                    key={b.id}
                    onClick={() => setSelectedId(b.id)}
                    className={`w-full text-left p-3 rounded-lg border text-xs transition-all flex justify-between items-center cursor-pointer ${
                      isSelected ? 'bg-white border-[#115e59] ring-1 ring-[#115e59]' : 'bg-white/80 border-gray-100 hover:bg-white'
                    }`}
                  >
                    <div className="min-w-0">
                      <span className="font-bold text-gray-900 block truncate">{b.name}</span>
                      <span className="text-[10px] text-gray-400 italic truncate block">
                        {b.isWelfareOnly ? t('welfareOnlyBadge') : (b.businessName || b.district)}
                      </span>
                    </div>
                    <span className={`shrink-0 ml-2 px-1.5 py-0.5 rounded text-[11px] font-bold ${
                      count > 0 ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : 'bg-gray-100 text-gray-400'
                    }`}>
                      {t('schemeCount', { count })}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Schemes detail + add form */}
        <div className="lg:col-span-2">
          {!selected ? (
            <div className="border border-dashed border-gray-200 rounded-xl p-12 text-center bg-white text-gray-400 h-full flex flex-col items-center justify-center">
              <HandHeart className="w-12 h-12 stroke-1 text-gray-300 mb-2" />
              {t('selectBeneficiaryPrompt')}
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-5">
              <div className="pb-3 border-b border-gray-50">
                <span className="text-[10px] bg-slate-100 text-slate-800 px-2 py-0.5 rounded font-bold font-mono">{t('idLabel')} {selected.id}</span>
                <h3 className="font-bold text-gray-800 text-sm mt-1">{selected.name}</h3>
                <span className="text-xs text-indigo-600 font-medium italic">{selected.businessName}</span>
              </div>

              {/* Existing schemes list */}
              <div>
                <h4 className="font-semibold text-gray-800 text-xs uppercase tracking-wider mb-2">{t('linkedSchemes', { count: schemes.length })}</h4>
                {schemes.length === 0 ? (
                  <div className="p-4 bg-slate-50 text-center rounded-lg text-xs text-gray-400">
                    {t('noSchemesLinkedYet')}
                  </div>
                ) : (
                  <div className="space-y-2.5 max-h-[260px] overflow-y-auto pr-1">
                    {schemes.map((s) => (
                      <div key={s.id} className="p-3 bg-slate-50 border border-gray-150 rounded-lg text-xs">
                        <div className="flex justify-between items-start">
                          <div className="flex items-center gap-2">
                            <Landmark className="w-3.5 h-3.5 text-[#115e59] shrink-0" />
                            <span className="font-bold text-gray-900">{s.schemeName}</span>
                          </div>
                          <button
                            onClick={() => handleRemoveScheme(s.id)}
                            title={t('removeLinkage')}
                            className="text-rose-400 hover:text-rose-600 cursor-pointer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2 text-[10px]">
                          <div className="flex items-center gap-1 text-gray-600">
                            <CalendarDays className="w-3 h-3 text-gray-400" />
                            <span>{s.dateOfLinkage}</span>
                          </div>
                          <div className="text-gray-600"><span className="text-gray-400">{t('benefitLabel')}</span> {s.benefitType}</div>
                          <div className="flex items-center gap-1 font-semibold text-emerald-700">
                            <Banknote className="w-3 h-3" />
                            {s.monetaryValue ? `₹${s.monetaryValue.toLocaleString('en-IN')}` : '—'}
                          </div>
                          {s.nonMonetarySupport && (
                            <div className="flex items-center gap-1 text-violet-700">
                              <Gift className="w-3 h-3" />
                              <span className="truncate">{s.nonMonetarySupport}</span>
                            </div>
                          )}
                        </div>
                        {s.notes && (
                          <p className="text-[10px] text-gray-500 mt-1.5 bg-white p-1.5 rounded border border-gray-100">{s.notes}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {lastSavedCount !== null && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-[11px] text-emerald-800 font-semibold animate-fade-in">
                  {t('schemeSavedConfirmation', { count: lastSavedCount })}
                </div>
              )}

              {/* Add scheme form */}
              <form onSubmit={handleAddScheme} className="bg-indigo-50/40 border border-indigo-100 rounded-lg p-4 space-y-3">
                <span className="font-bold text-indigo-900 text-xs uppercase tracking-wider flex items-center gap-1.5">
                  <Plus className="w-3.5 h-3.5" /> {t('linkNewScheme')}
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('schemeNameLabel')}</label>
                    <select
                      value={schemeName}
                      onChange={(e) => setSchemeName(e.target.value)}
                      className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                    >
                      {COMMON_SCHEMES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    {schemeName === 'Other' && (
                      <input
                        type="text"
                        value={customSchemeName}
                        onChange={(e) => setCustomSchemeName(e.target.value)}
                        placeholder={t('enterSchemeNamePlaceholder')}
                        className="w-full text-xs border border-gray-200 p-2 rounded mt-2"
                      />
                    )}
                  </div>
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('dateOfLinkageLabel')}</label>
                    <input
                      type="date"
                      required
                      value={dateOfLinkage}
                      onChange={(e) => setDateOfLinkage(e.target.value)}
                      className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('typeOfBenefitLabel')}</label>
                    <select
                      value={benefitType}
                      onChange={(e) => setBenefitType(e.target.value)}
                      className="w-full text-xs border border-gray-200 p-2 rounded bg-white"
                    >
                      {BENEFIT_TYPES.map(bt => <option key={bt} value={bt}>{bt}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('monetaryValueLabel')}</label>
                    <input
                      type="number"
                      min={0}
                      value={monetaryValue}
                      onChange={(e) => setMonetaryValue(e.target.value === '' ? '' : Number(e.target.value))}
                      placeholder={t('monetaryValuePlaceholder')}
                      className="w-full text-xs border border-gray-200 p-2 rounded font-mono"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('nonMonetarySupportLabel')}</label>
                    <input
                      type="text"
                      value={nonMonetarySupport}
                      onChange={(e) => setNonMonetarySupport(e.target.value)}
                      placeholder={t('nonMonetarySupportPlaceholder')}
                      className="w-full text-xs border border-gray-200 p-2 rounded"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase mb-1">{t('notesLabel')}</label>
                    <input
                      type="text"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder={t('notesPlaceholder')}
                      className="w-full text-xs border border-gray-200 p-2 rounded"
                    />
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={saving}
                  className="w-full bg-[#115e59] hover:bg-[#0f766e] disabled:opacity-60 border-b-2 border-[#0284c7] text-white font-bold text-xs py-2 rounded cursor-pointer uppercase tracking-wider"
                >
                  {saving ? t('saving') : t('addSchemeLinkage')}
                </button>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
