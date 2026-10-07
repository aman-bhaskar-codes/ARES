import React, { useState } from 'react';
import type { ExportCreate } from '@/lib/api/types';

interface ExportDialogProps {
  runId: string;
  isOpen: boolean;
  onClose: () => void;
  onExport: (request: ExportCreate) => Promise<void>;
}

export function ExportDialog({ runId, isOpen, onClose, onExport }: ExportDialogProps) {
  const [format, setFormat] = useState<ExportCreate['format']>('markdown');
  const [isExporting, setIsExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsExporting(true);
    setError(null);
    try {
      await onExport({ format });
      onClose();
    } catch (err: any) {
      setError(err.message || 'An error occurred during export.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-dialog-title"
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <h2 id="export-dialog-title" className="text-xl font-bold text-gray-900 mb-4">
          Export Research Report
        </h2>
        
        <form onSubmit={handleExport}>
          <fieldset className="mb-6">
            <legend className="text-sm font-medium text-gray-700 mb-2">Select Export Format</legend>
            <div className="space-y-3">
              {[
                { value: 'markdown', label: 'Markdown', desc: 'Raw text with Markdown formatting.' },
                { value: 'html', label: 'HTML', desc: 'Sanitized HTML document for the web.' },
                { value: 'pdf', label: 'PDF', desc: 'Printable document (requires local renderer).' },
                { value: 'json', label: 'JSON Manifest', desc: 'Structured data containing evidence and claims.' }
              ].map((opt) => (
                <div key={opt.value} className="flex items-start">
                  <div className="flex items-center h-5">
                    <input
                      id={`format-${opt.value}`}
                      name="export-format"
                      type="radio"
                      value={opt.value}
                      checked={format === opt.value}
                      onChange={(e) => setFormat(e.target.value as any)}
                      className="focus:ring-blue-500 h-4 w-4 text-blue-600 border-gray-300"
                    />
                  </div>
                  <div className="ml-3 text-sm">
                    <label htmlFor={`format-${opt.value}`} className="font-medium text-gray-700">
                      {opt.label}
                    </label>
                    <p className="text-gray-500">{opt.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </fieldset>

          {error && (
            <div className="mb-4 p-3 bg-red-50 text-red-700 border border-red-200 rounded text-sm" role="alert">
              {error}
            </div>
          )}

          <div className="flex justify-end space-x-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              disabled={isExporting}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isExporting}
              className="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
            >
              {isExporting ? 'Exporting...' : 'Generate Export'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
