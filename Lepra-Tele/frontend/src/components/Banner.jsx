const KIND_CLS = {
  error: 'border-red-200 bg-red-50 text-red-700',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  info: 'border-emerald-200 bg-emerald-50 text-emerald-800',
};

export default function Banner({ kind = 'info', className = '', children }) {
  return (
    <div className={`text-sm rounded-lg border px-3.5 py-2.5 ${KIND_CLS[kind] || KIND_CLS.info} ${className}`}>
      {children}
    </div>
  );
}
