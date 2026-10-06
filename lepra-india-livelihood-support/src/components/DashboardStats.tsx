import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Beneficiary } from '../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import {
  TrendingUp, Wallet, ShieldCheck, Percent, Users, HeartPulse, Building2, SlidersHorizontal, Landmark, X
} from 'lucide-react';
import { normalizeStateName } from '../utils/normalizeState';
import { normalizeDistrictName } from '../utils/districts';

interface DashboardStatsProps {
  beneficiaries: Beneficiary[];
}

const ALL = '__ALL__';

export default function DashboardStats({ beneficiaries }: DashboardStatsProps) {
  const { t } = useTranslation('dashboardStats');

  // --- Filters: Project / State / District, so any of these slices can be pulled on demand ---
  const [filterProject, setFilterProject] = useState(ALL);
  const [filterState, setFilterState] = useState(ALL);
  const [filterDistrict, setFilterDistrict] = useState(ALL);
  const [breakdownDimension, setBreakdownDimension] = useState<'projectName' | 'state' | 'district'>('projectName');
  // Row selected in the breakdown table, so its full patient roster can be shown in a modal.
  const [selectedBreakdownKey, setSelectedBreakdownKey] = useState<string | null>(null);

  const projectOptions = useMemo(
    () => Array.from(new Set(beneficiaries.map(b => b.projectName).filter((v): v is string => !!v))).sort(),
    [beneficiaries]
  );
  const stateOptions = useMemo(
    () => Array.from(new Set(beneficiaries.map(b => b.state ? normalizeStateName(b.state) : '').filter(Boolean))).sort(),
    [beneficiaries]
  );
  // District options cascade off the selected state so the list stays relevant.
  const districtOptions = useMemo(() => {
    const pool = filterState === ALL ? beneficiaries : beneficiaries.filter(b => normalizeStateName(b.state) === filterState);
    return Array.from(new Set(pool.map(b => b.district ? normalizeDistrictName(b.district, b.state) : '').filter(Boolean))).sort();
  }, [beneficiaries, filterState]);

  const beneficiariesFiltered = useMemo(() => beneficiaries.filter(b =>
    (filterProject === ALL || b.projectName === filterProject) &&
    (filterState === ALL || normalizeStateName(b.state) === filterState) &&
    (filterDistrict === ALL || normalizeDistrictName(b.district, b.state) === filterDistrict)
  ), [beneficiaries, filterProject, filterState, filterDistrict]);

  // The loan/livelihood portfolio (business plan, SOP recovery, geo-verification) only ever
  // covers beneficiaries who came through the Secure Intake Form — welfare-only beneficiaries
  // added directly from the Welfare Schemes module are excluded from these views.
  const beneficiaries_ = beneficiariesFiltered.filter(b => !b.isWelfareOnly);

  // Project/State/District-wise breakdown across the three livelihood components
  const breakdownRows = useMemo(() => {
    const map = new Map<string, { key: string; individualLoans: number; groupLoans: number; schemeLinkages: number; totalDisbursed: number; patients: Beneficiary[] }>();
    beneficiariesFiltered.forEach(b => {
      const rawValue = b[breakdownDimension] as string | undefined;
      const key = rawValue
        ? (breakdownDimension === 'state'
          ? normalizeStateName(rawValue)
          : breakdownDimension === 'district'
            ? normalizeDistrictName(rawValue, b.state)
            : rawValue)
        : t('unassigned');
      const row = map.get(key) || { key, individualLoans: 0, groupLoans: 0, schemeLinkages: 0, totalDisbursed: 0, patients: [] };
      if (!b.isWelfareOnly) {
        if (b.type === 'Individual') row.individualLoans += 1;
        else row.groupLoans += 1;
        row.totalDisbursed += b.approvedAmount || 0;
      }
      row.schemeLinkages += Array.isArray(b.welfareSchemes) ? b.welfareSchemes.length : 0;
      row.patients.push(b);
      map.set(key, row);
    });
    return Array.from(map.values()).sort((a, b) => a.key.localeCompare(b.key));
  }, [beneficiariesFiltered, breakdownDimension, t]);

  const selectedBreakdownRow = useMemo(
    () => breakdownRows.find(r => r.key === selectedBreakdownKey) || null,
    [breakdownRows, selectedBreakdownKey]
  );

  // 1. Compute summary numbers safely
  const disbursedList = beneficiaries_.filter(b =>
    b.status === 'Disbursed' || b.status === 'Verified Active'
  );



  const totalDisbursed = disbursedList.reduce((acc, b) => acc + (b.approvedAmount || 0), 0);

  const totalRecovered = beneficiaries_.reduce((acc, b) => {
    const paidSum = b.payments?.reduce((pAcc, p) => pAcc + p.amount, 0) || 0;
    return acc + paidSum;
  }, 0);

  const remainingBalance = totalDisbursed - totalRecovered;

  // Compliance Rate = On-time paid installments / Total due installments (excluding upcoming pending ones)
  // Let's compute actual schedule statistics to see compliance metrics.
  let totalDueInstallments = 0;
  let paidDueInstallments = 0;

  beneficiaries_.forEach(b => {
    b.emiSchedule?.forEach(item => {
      // For demo compliance: if the item is "Paid", it's marked.
      // If it's overdue or paid, it represents an installment that should have been dealt with.
      if (item.status === 'Paid') {
        paidDueInstallments++;
        totalDueInstallments++;
      } else if (item.status === 'Overdue') {
        totalDueInstallments++;
      } else {
        // Pending: check if the dueDate has passed to consider it "due" & non-compliant.
        // Today's date is 2026-05-27 in development metadata.
        const today = new Date("2026-05-27");
        const dueDate = new Date(item.dueDate);
        if (dueDate < today) {
          totalDueInstallments++;
        }
      }
    });
  });

  const complianceRate = totalDueInstallments > 0 
    ? Math.round((paidDueInstallments / totalDueInstallments) * 100) 
    : 100;

  // 2. Prepare chart data
  // Distribution by Disease Type
  const leprosyCount = beneficiaries_.filter(b => b.diseaseType === 'Leprosy').length;
  const leptoCount = beneficiaries_.filter(b => b.diseaseType === 'Leptospirosis').length;
  const lfCount = beneficiaries_.filter(b => b.diseaseType === 'LF').length;

  const diseaseData = [
    ...(leprosyCount > 0 ? [{ name: t('leprosyCases'), value: leprosyCount, color: '#115e59' }] : []),
    ...(leptoCount > 0 ? [{ name: t('leptospirosisCases'), value: leptoCount, color: '#0284c7' }] : []),
    ...(lfCount > 0 ? [{ name: t('lfCases'), value: lfCount, color: '#0ea5e9' }] : [])
  ];

  // Distribution by Beneficiary Type (Individual Loans vs Group Loans / Cooperative Group)
  const individualCount = beneficiaries_.filter(b => b.type === 'Individual').length;
  const groupCount = beneficiaries_.filter(b => b.type === 'Group').length;

  const typeData = [
    { name: t('individualType'), value: individualCount, color: '#1e40af' }, // Royal Blue
    { name: t('cooperativeGroup'), value: groupCount, color: '#0ea5e9' } // Vivid Orange
  ];

  // Recovery timeline data per registered active beneficiary
  const recoveryDetailsData = disbursedList.map(b => {
    const recovered = b.payments?.reduce((sum, p) => sum + p.amount, 0) || 0;
    const pending = (b.approvedAmount || 0) - recovered;
    return {
      name: b.name.split(' ')[0], // short name
      Disbursed: b.approvedAmount || 0,
      Recovered: recovered,
      'Pending Balance': pending
    };
  });

  // Business Sector Startups
  const sectors = beneficiaries_.reduce((acc: { [key: string]: number }, b) => {
    const sector = b.businessSector || 'Other';
    acc[sector] = (acc[sector] || 0) + 1;
    return acc;
  }, {});

  const sectorChartData = Object.keys(sectors).map(key => ({
    sector: key,
    count: sectors[key]
  }));

  return (
    <div className="space-y-4" id="dashboard_stats_wrapper">
      {/* Project / State / District filters — apply across every section below */}
      <div className="bg-white p-3.5 rounded-lg border border-gray-200 shadow-2xs">
        <div className="flex items-center gap-1.5 mb-2.5">
          <SlidersHorizontal className="w-3.5 h-3.5 text-[#0284c7]" />
          <span className="text-[10px] font-bold text-[#115e59] uppercase tracking-wider">{t('filters.title')}</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <div>
            <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">{t('filters.project')}</label>
            <select
              value={filterProject}
              onChange={(e) => setFilterProject(e.target.value)}
              className="w-full text-xs border border-gray-200 p-2 rounded-lg bg-white"
            >
              <option value={ALL}>{t('filters.allProjects')}</option>
              {projectOptions.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">{t('filters.state')}</label>
            <select
              value={filterState}
              onChange={(e) => { setFilterState(e.target.value); setFilterDistrict(ALL); }}
              className="w-full text-xs border border-gray-200 p-2 rounded-lg bg-white"
            >
              <option value={ALL}>{t('filters.allStates')}</option>
              {stateOptions.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">{t('filters.district')}</label>
            <select
              value={filterDistrict}
              onChange={(e) => setFilterDistrict(e.target.value)}
              className="w-full text-xs border border-gray-200 p-2 rounded-lg bg-white"
            >
              <option value={ALL}>{t('filters.allDistricts')}</option>
              {districtOptions.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>
        {(filterProject !== ALL || filterState !== ALL || filterDistrict !== ALL) && (
          <button
            type="button"
            onClick={() => { setFilterProject(ALL); setFilterState(ALL); setFilterDistrict(ALL); }}
            className="mt-2.5 text-[10px] font-bold text-[#115e59] hover:text-[#0284c7] underline cursor-pointer"
          >
            {t('filters.reset')}
          </button>
        )}
      </div>

      {/* Metric Cards Bento Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Disbursed */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider block">{t('totalDisbursed')}</span>
            <span className="text-xl font-bold font-mono text-gray-900 block mt-0.5">₹{totalDisbursed.toLocaleString('en-IN')}</span>
            <div className="flex items-center gap-1 mt-1 text-[10px] text-slate-500">
              <span className="px-1 py-0.2 bg-emerald-50 text-emerald-700 font-bold rounded">{t('zeroInterestSop')}</span>
              <span>{t('livelihoodSupport')}</span>
            </div>
          </div>
          <div className="p-2.5 bg-[#115e59]/10 rounded-md text-[#115e59]">
            <Wallet className="w-5 h-5" />
          </div>
        </div>

        {/* Card 2: Total Recovered */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider block">{t('totalRecovered')}</span>
            <span className="text-xl font-bold font-mono text-emerald-700 block mt-0.5">₹{totalRecovered.toLocaleString('en-IN')}</span>
            <div className="flex items-center gap-1 mt-1 text-[10px] text-emerald-700 font-bold">
              <TrendingUp className="w-3 h-3" />
              <span>{t('rotatedBackToReserve')}</span>
            </div>
          </div>
          <div className="p-2.5 bg-emerald-50 rounded-md text-emerald-700">
            <ShieldCheck className="w-5 h-5" />
          </div>
        </div>

        {/* Card 3: Outstanding support balance */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider block">{t('outstandingSupport')}</span>
            <span className="text-xl font-bold font-mono text-amber-700 block mt-0.5">₹{remainingBalance.toLocaleString('en-IN')}</span>
            <span className="text-[10px] text-gray-400 block mt-1">{t('activelyTrackedRecovery')}</span>
          </div>
          <div className="p-2.5 bg-amber-50 rounded-md text-amber-700">
            <Percent className="w-5 h-5" />
          </div>
        </div>

        {/* Card 4: Repayment Compliance */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs flex items-center justify-between">
          <div>
            <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider block">{t('complianceRate')}</span>
            <span className="text-xl font-bold font-mono text-[#115e59] block mt-0.5">{complianceRate}%</span>
            <span className="text-[10px] text-[#115e59]/80 font-bold block mt-1">{t('onTimeEmiRecovery')}</span>
          </div>
          <div className="p-2.5 bg-[#115e59]/10 rounded-md text-[#115e59]">
            <ShieldCheck className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Recharts Data Visualization Dashboard Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Recovery Progress Bar Chart */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-xs lg:col-span-2">
          <h3 className="text-xs font-bold text-[#115e59] uppercase tracking-wider mb-3 flex items-center gap-1.5">
            <TrendingUp className="w-4 h-4 text-[#0284c7]" />
            {t('recoveryPortfolioBalances')}
          </h3>
          <div className="h-[250px]">
            {recoveryDetailsData.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-400 text-[11px]">
                {t('noActiveDisbursements')}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={recoveryDetailsData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                  <YAxis stroke="#64748b" fontSize={10} tickFormatter={(val) => `₹${val}`} />
                  <Tooltip formatter={(value) => `₹${value}`} />
                  <Legend wrapperStyle={{ fontSize: '10px', paddingTop: '5px' }} />
                  <Bar dataKey="Disbursed" fill="#115e59" name={t('approvedSupport')} radius={[2, 2, 0, 0]} />
                  <Bar dataKey="Recovered" fill="#0284c7" name={t('recoveredAmount')} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Distribution Pie Charts */}
        <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-xs space-y-4 flex flex-col justify-between">
          <div>
            <h3 className="text-xs font-bold text-[#115e59] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <HeartPulse className="w-4 h-4 text-[#0284c7]" />
              {t('distributionSupportStructure')}
            </h3>

            <div className="grid grid-cols-2 gap-3">
              {/* Disease Type Pie */}
              <div className="flex flex-col items-center">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-1">{t('diagnosis')}</span>
                <div className="w-full h-[110px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={diseaseData}
                        cx="50%"
                        cy="50%"
                        innerRadius={20}
                        outerRadius={40}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {diseaseData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex flex-col gap-1 text-[11px] mt-1.5 self-start w-full font-mono">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#115e59]"></span>{t('leprosy')}</span>
                    <span className="font-bold">{leprosyCount}</span>
                  </div>
                  {leptoCount > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#0284c7]"></span>{t('lepto')}</span>
                      <span className="font-bold">{leptoCount}</span>
                    </div>
                  )}
                  {lfCount > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#0ea5e9]"></span>{t('lf')}</span>
                      <span className="font-bold">{lfCount}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Beneficiary Type Pie */}
              <div className="flex flex-col items-center">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest block mb-1">{t('structure')}</span>
                <div className="w-full h-[110px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={typeData}
                        cx="50%"
                        cy="50%"
                        innerRadius={20}
                        outerRadius={40}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {typeData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex flex-col gap-1 text-[11px] mt-1.5 self-start w-full font-mono">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-700"></span>{t('individual')}</span>
                    <span className="font-bold">{individualCount}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-sky-500"></span>{t('group')}</span>
                    <span className="font-bold">{groupCount}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Sectors and Compliance Report table */}
      <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs">
        <h3 className="text-xs font-bold text-[#115e59] uppercase tracking-wider mb-3 flex items-center gap-1.5">
          <Building2 className="w-4 h-4 text-[#0284c7]" />
          {t('enterpriseSectorsCompliance')}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* List of Sectors */}
          <div>
            <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider block mb-2">{t('enterpriseSectorsOverview')}</span>
            <div className="flex flex-wrap gap-1.5">
              {sectorChartData.map((s, idx) => (
                <div key={idx} className="flex items-center gap-2 bg-[#ffffff] border border-gray-200 rounded px-2.5 py-1">
                  <span className="text-[11px] font-bold text-[#171717]">{s.sector}</span>
                  <span className="text-[11px] px-1 py-0.2 rounded bg-[#115e59] text-[#0284c7] font-bold">{t('casesCount', { count: s.count })}</span>
                </div>
              ))}
            </div>
          </div>

          {/* SOP Compliance checklist metrics */}
          <div className="space-y-2">
            <span className="text-[10px] text-gray-400 font-bold uppercase tracking-wider block">{t('sopStandardsChecklist')}</span>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-emerald-50 border border-emerald-100 p-2 rounded">
                <span className="text-slate-500 block text-[11px] font-mono">{t('interestCharged')}</span>
                <span className="font-bold text-emerald-800 font-mono text-xs">{t('zeroRate')}</span>
              </div>
              <div className="bg-[#115e59]/5 border border-[#115e59]/10 p-2 rounded">
                <span className="text-slate-500 block text-[11px] font-mono">{t('emiMilestones')}</span>
                <span className="font-bold text-[#115e59] font-mono text-xs">{t('variableFlow')}</span>
              </div>
              <div className="bg-blue-50 border border-blue-100 p-2 rounded justify-between flex flex-col">
                <span className="text-slate-500 block text-[11px] font-mono">{t('geoTagGpsRate')}</span>
                <span className="font-bold text-blue-800 font-mono text-xs">
                  {t('verifiedPercent', {
                    percent: disbursedList.length > 0
                      ? Math.round((disbursedList.filter(b => b.verification?.isCompleted).length / disbursedList.length) * 100)
                      : 100
                  })}
                </span>
              </div>
              <div className="bg-sky-50 border border-sky-100 p-2 rounded justify-between flex flex-col">
                <span className="text-slate-500 block text-[11px] font-mono">{t('activeStartups')}</span>
                <span className="font-bold text-[#0284c7] font-mono text-xs">
                  {t('unitsLive', { count: beneficiaries_.filter(b => b.status === 'Verified Active').length })}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Project / State / District-wise breakdown of Scheme Linkages, Individual Loans & Group Loans */}
      <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-2xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
          <h3 className="text-xs font-bold text-[#115e59] uppercase tracking-wider flex items-center gap-1.5">
            <Landmark className="w-4 h-4 text-[#0284c7]" />
            {t('breakdown.title')}
          </h3>
          <div className="flex bg-slate-50 border border-gray-200 rounded-full p-0.5 gap-0.5 w-fit">
            {(['projectName', 'state', 'district'] as const).map((dim) => (
              <button
                key={dim}
                type="button"
                onClick={() => setBreakdownDimension(dim)}
                className={`px-3 py-1 text-[10px] font-bold uppercase tracking-wide rounded-full transition-all cursor-pointer ${
                  breakdownDimension === dim ? 'bg-[#115e59] text-white shadow-xs' : 'text-gray-500 hover:bg-white'
                }`}
              >
                {t(`breakdown.dimension.${dim}`)}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs min-w-[560px]">
            <thead>
              <tr className="bg-slate-50 text-[11px] uppercase tracking-wider text-gray-500 border-b border-gray-200">
                <th className="p-2.5 px-3">{t(`breakdown.dimension.${breakdownDimension}`)}</th>
                <th className="p-2.5 px-3 text-right">{t('breakdown.individualLoans')}</th>
                <th className="p-2.5 px-3 text-right">{t('breakdown.groupLoans')}</th>
                <th className="p-2.5 px-3 text-right">{t('breakdown.schemeLinkages')}</th>
                <th className="p-2.5 px-3 text-right">{t('breakdown.totalDisbursed')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {breakdownRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-gray-400 text-xs">{t('breakdown.empty')}</td>
                </tr>
              ) : (
                breakdownRows.map((row) => (
                  <tr
                    key={row.key}
                    onClick={() => setSelectedBreakdownKey(row.key)}
                    className="hover:bg-sky-50/30 transition-colors cursor-pointer"
                  >
                    <td className="p-2.5 px-3 font-semibold text-[#171717]">{row.key}</td>
                    <td className="p-2.5 px-3 text-right font-mono text-blue-800">{row.individualLoans}</td>
                    <td className="p-2.5 px-3 text-right font-mono text-sky-700">{row.groupLoans}</td>
                    <td className="p-2.5 px-3 text-right font-mono text-emerald-700">{row.schemeLinkages}</td>
                    <td className="p-2.5 px-3 text-right font-mono text-[#115e59]">₹{row.totalDisbursed.toLocaleString('en-IN')}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Patient roster modal: full name list for the clicked breakdown row (e.g. a single district) */}
      {selectedBreakdownRow && (
        <div
          className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4 z-50"
          onClick={() => setSelectedBreakdownKey(null)}
        >
          <div
            className="bg-white rounded-xl shadow-lg border border-gray-100 max-w-lg w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 bg-teal-950 text-white flex justify-between items-center sticky top-0">
              <div>
                <h3 className="font-semibold text-sm">{selectedBreakdownRow.key}</h3>
                <p className="text-[10px] text-slate-300 mt-0.5">
                  {t('breakdown.rosterModal.totalPatients', { count: selectedBreakdownRow.patients.length })}
                </p>
              </div>
              <button
                onClick={() => setSelectedBreakdownKey(null)}
                className="text-white hover:text-red-400 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="divide-y divide-gray-100">
              {selectedBreakdownRow.patients.length === 0 ? (
                <p className="p-6 text-center text-gray-400 text-xs">{t('breakdown.rosterModal.empty')}</p>
              ) : (
                [...selectedBreakdownRow.patients]
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((b) => (
                    <div key={b.id} className="p-3 px-4 flex items-center justify-between gap-3">
                      <div>
                        <span className="font-semibold text-gray-900 text-xs block">{b.name}</span>
                        <span className="text-[10px] text-gray-400 font-mono">{normalizeDistrictName(b.district, b.state)}, {normalizeStateName(b.state)}</span>
                      </div>
                      <span className="text-[10px] bg-rose-50 text-rose-800 font-semibold px-2 py-0.5 rounded border border-rose-100 shrink-0">
                        {b.diseaseType}
                      </span>
                    </div>
                  ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
