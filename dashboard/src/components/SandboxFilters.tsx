import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Filter, X, Plus, Trash2, Search } from 'lucide-react';
import { useApp } from '@/contexts/AppContext';
import type { SandboxStatus, Template } from '@/types/sandbox';

export interface SandboxFiltersState {
  template_id?: string;
  status?: SandboxStatus;
  pool_state?: string;
  name?: string;
  metadata?: Record<string, string>;
}

interface SandboxFiltersProps {
  filters: SandboxFiltersState;
  onFiltersChange: (filters: SandboxFiltersState) => void;
  onSearch: () => void;
  onReset: () => void;
  templates?: Template[];
}

export function SandboxFilters({
  filters,
  onFiltersChange,
  onSearch,
  onReset,
  templates = [],
}: SandboxFiltersProps) {
  const { t } = useApp();
  const [metadataKey, setMetadataKey] = useState('');
  const [metadataValue, setMetadataValue] = useState('');

  const handleAddMetadata = () => {
    if (!metadataKey || !metadataValue) return;

    onFiltersChange({
      ...filters,
      metadata: {
        ...filters.metadata,
        [metadataKey]: metadataValue,
      },
    });

    setMetadataKey('');
    setMetadataValue('');
  };

  const handleRemoveMetadata = (key: string) => {
    const newMetadata = { ...filters.metadata };
    delete newMetadata[key];

    onFiltersChange({
      ...filters,
      metadata: Object.keys(newMetadata).length > 0 ? newMetadata : undefined,
    });
  };

  const hasActiveFilters =
    filters.template_id ||
    filters.status ||
    (filters.pool_state && filters.pool_state !== 'user-sandboxes') ||
    filters.name ||
    (filters.metadata && Object.keys(filters.metadata).length > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Filter className="h-5 w-5" />
          Filters
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Basic Filters */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Template */}
          <div className="space-y-2">
            <Label htmlFor="filter-template">Template</Label>
            <Select
              value={filters.template_id || 'all'}
              onValueChange={(value) =>
                onFiltersChange({
                  ...filters,
                  template_id: value === 'all' ? undefined : value
                })
              }
            >
              <SelectTrigger id="filter-template">
                <SelectValue placeholder="All templates" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All templates</SelectItem>
                {templates.map((template) => (
                  <SelectItem key={template.id} value={template.id}>
                    {template.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Status */}
          <div className="space-y-2">
            <Label htmlFor="filter-status">Status</Label>
            <Select
              value={filters.status || 'all'}
              onValueChange={(value) =>
                onFiltersChange({
                  ...filters,
                  status: value === 'all' ? undefined : (value as SandboxStatus)
                })
              }
            >
              <SelectTrigger id="filter-status">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="creating">Creating</SelectItem>
                <SelectItem value="created">Created</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="stopped">Stopped</SelectItem>
                <SelectItem value="exited">Exited</SelectItem>
                <SelectItem value="pooled">Pooled</SelectItem>
                <SelectItem value="unknown">Unknown</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Pool State */}
          <div className="space-y-2">
            <Label htmlFor="filter-pool-state">Pool State</Label>
            <Select
              value={filters.pool_state || 'user-sandboxes'}
              onValueChange={(value) =>
                onFiltersChange({
                  ...filters,
                  pool_state: value === 'all' ? undefined : value
                })
              }
            >
              <SelectTrigger id="filter-pool-state">
                <SelectValue placeholder="User sandboxes (default)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user-sandboxes">User Sandboxes (allocated or direct)</SelectItem>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="none">Direct (none)</SelectItem>
                <SelectItem value="creating">Creating</SelectItem>
                <SelectItem value="available">Available</SelectItem>
                <SelectItem value="allocated">Allocated</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="filter-name">Name</Label>
            <Input
              id="filter-name"
              placeholder="Search by name..."
              value={filters.name || ''}
              onChange={(e) =>
                onFiltersChange({ ...filters, name: e.target.value || undefined })
              }
            />
          </div>
        </div>

        {/* Metadata Filters */}
        <div className="space-y-3 pt-4 border-t">
          <Label className="text-base">Metadata Filters</Label>

          {/* Active Metadata Filters */}
          {filters.metadata && Object.keys(filters.metadata).length > 0 && (
            <div className="space-y-2">
              {Object.entries(filters.metadata).map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center gap-2 p-2 bg-muted rounded-md"
                >
                  <code className="text-sm flex-1">
                    <span className="font-semibold">{key}</span> = {value}
                  </code>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRemoveMetadata(key)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {/* Add Metadata Filter */}
          <div className="flex gap-2">
            <Input
              placeholder="Key (e.g., user_id)"
              value={metadataKey}
              onChange={(e) => setMetadataKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAddMetadata();
                }
              }}
            />
            <Input
              placeholder="Value (e.g., user-123)"
              value={metadataValue}
              onChange={(e) => setMetadataValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAddMetadata();
                }
              }}
            />
            <Button
              onClick={handleAddMetadata}
              disabled={!metadataKey || !metadataValue}
            >
              <Plus className="h-4 w-4 mr-2" />
              Add
            </Button>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2 pt-4 border-t">
          <Button onClick={onSearch} className="flex-1">
            <Search className="h-4 w-4 mr-2" />
            Search
          </Button>
          {hasActiveFilters && (
            <Button variant="outline" onClick={onReset}>
              <X className="h-4 w-4 mr-2" />
              Clear
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
