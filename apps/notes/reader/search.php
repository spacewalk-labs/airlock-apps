<?php
declare(strict_types=1);

// Folio search endpoint. It keeps Perlite's same-origin search surface while
// returning enough structure for accessible results and exact line locations.
const FOLIO_MAX_FILE_BYTES = 2097152;
const FOLIO_MAX_RESULTS = 80;
const FOLIO_MATCHES_PER_FILE = 3;

function folio_tokens(string $query): array
{
    $parts = preg_split('/\s+/u', trim($query), -1, PREG_SPLIT_NO_EMPTY);
    return is_array($parts) ? array_slice($parts, 0, 12) : [];
}

function folio_contains_all(string $text, array $tokens): bool
{
    foreach ($tokens as $token) {
        if (stripos($text, $token) === false) {
            return false;
        }
    }
    return true;
}

function folio_clean_line(string $line): string
{
    $line = preg_replace('/^\s*(?:#{1,6}|>|[-*+]\s|\d+[.)]\s)\s*/u', '', $line) ?? $line;
    $line = preg_replace('/\s+/u', ' ', trim($line)) ?? trim($line);
    $characters = preg_split('//u', $line, -1, PREG_SPLIT_NO_EMPTY);
    if (is_array($characters) && count($characters) > 220) {
        return implode('', array_slice($characters, 0, 217)) . '…';
    }
    return $line;
}

function folio_first_summary(array $lines): string
{
    $frontmatter = isset($lines[0]) && trim($lines[0]) === '---';
    foreach ($lines as $index => $line) {
        $trimmed = trim($line);
        if ($frontmatter) {
            if ($index > 0 && $trimmed === '---') {
                $frontmatter = false;
            }
            continue;
        }
        $clean = folio_clean_line($line);
        if ($clean !== '') {
            return $clean;
        }
    }
    return '본문 미리보기가 없습니다.';
}

function folio_markdown_files(string $root): array
{
    $files = [];
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::LEAVES_ONLY
    );
    foreach ($iterator as $file) {
        if (!$file instanceof SplFileInfo || !$file->isFile() || $file->isLink()) {
            continue;
        }
        if (strtolower($file->getExtension()) !== 'md' || $file->getSize() > FOLIO_MAX_FILE_BYTES) {
            continue;
        }
        $relative = substr($file->getPathname(), strlen($root) + 1);
        $segments = preg_split('~/+~', $relative) ?: [];
        if (array_filter($segments, static fn(string $segment): bool => str_starts_with($segment, '.'))) {
            continue;
        }
        if (isset($segments[0]) && in_array($segments[0], ['Library', 'Repositories', '휴지통'], true)) {
            continue;
        }
        $files[] = $file;
    }
    return $files;
}

function folio_search(string $root, string $query): array
{
    $started = hrtime(true);
    $tokens = folio_tokens($query);
    $rows = [];
    $files = folio_markdown_files($root);

    foreach ($files as $file) {
        $path = str_replace(DIRECTORY_SEPARATOR, '/', substr($file->getPathname(), strlen($root) + 1));
        $page = preg_replace('/\.md$/i', '', $path) ?? $path;
        $contents = file_get_contents($file->getPathname());
        if (!is_string($contents)) {
            continue;
        }
        $lines = preg_split('/\R/u', $contents) ?: [];
        $modified = $file->getMTime() * 1000;

        if ($tokens === []) {
            $rows[] = [
                'page' => $page,
                'line' => 1,
                'snippet' => folio_first_summary($lines),
                'modified' => $modified,
                'match' => 'recent',
            ];
            continue;
        }

        $matches = 0;
        if (folio_contains_all($page, $tokens)) {
            $rows[] = [
                'page' => $page,
                'line' => 1,
                'snippet' => folio_first_summary($lines),
                'modified' => $modified,
                'match' => 'title',
            ];
            $matches++;
        }
        foreach ($lines as $index => $line) {
            if ($matches >= FOLIO_MATCHES_PER_FILE || count($rows) >= FOLIO_MAX_RESULTS) {
                break;
            }
            if (trim($line) === '' || !folio_contains_all($line, $tokens)) {
                continue;
            }
            $rows[] = [
                'page' => $page,
                'line' => $index + 1,
                'snippet' => folio_clean_line($line),
                'modified' => $modified,
                'match' => 'body',
            ];
            $matches++;
        }
        if (count($rows) >= FOLIO_MAX_RESULTS) {
            break;
        }
    }

    usort($rows, static function (array $left, array $right): int {
        $rank = ['title' => 0, 'body' => 1, 'recent' => 2];
        $kind = ($rank[$left['match']] ?? 3) <=> ($rank[$right['match']] ?? 3);
        return $kind !== 0 ? $kind : ($right['modified'] <=> $left['modified']);
    });
    if ($tokens === []) {
        $rows = array_slice($rows, 0, 12);
    }

    return [
        'query' => trim($query),
        'results' => array_slice($rows, 0, FOLIO_MAX_RESULTS),
        'files_scanned' => count($files),
        'elapsed_ms' => round((hrtime(true) - $started) / 1000000, 2),
    ];
}

$root = PHP_SAPI === 'cli' ? ($argv[1] ?? '') : '/var/www/perlite/notes';
$query = PHP_SAPI === 'cli' ? ($argv[2] ?? '') : (string) ($_GET['q'] ?? '');
$root = realpath($root) ?: '';
if ($root === '' || !is_dir($root) || strlen($query) > 240) {
    if (PHP_SAPI !== 'cli') {
        http_response_code(400);
    }
    echo json_encode(['error' => 'invalid search request'], JSON_UNESCAPED_UNICODE) . "\n";
    exit(1);
}

if (PHP_SAPI !== 'cli') {
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    header('X-Content-Type-Options: nosniff');
}
echo json_encode(folio_search($root, $query), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";
