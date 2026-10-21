/** Ratchet for legacy silent fallbacks. New exceptions need an inline reason. */
import ts from 'typescript';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const budgetPath = resolve(root, '../docs/compliance/fallback-budget.v1.json');

function emptyValue(node) {
  if (!node) return false;
  if (node.kind === ts.SyntaxKind.NullKeyword) return true;
  if (ts.isArrayLiteralExpression(node)) return node.elements.length === 0;
  if (ts.isObjectLiteralExpression(node)) return node.properties.length === 0;
  if (ts.isIdentifier(node)) return node.text === 'EMPTY';
  return false;
}

export function findFallbacks(source, filename = 'source.ts') {
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  const found = [];
  function visit(node) {
    if (ts.isCallExpression(node)) {
      const expression = node.expression;
      const callback = node.arguments[0];
      let silent = false;
      if (ts.isIdentifier(expression) && expression.text === 'catchError' && callback) {
        const inspect = (child) => {
          if (ts.isIdentifier(child) && child.text === 'EMPTY') silent = true;
          if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
            && child.expression.text === 'of' && child.arguments.some(emptyValue)) silent = true;
          ts.forEachChild(child, inspect);
        };
        inspect(callback);
      }
      // Moving catchError into the compatibility helper does not retire its
      // default fallback. Count every remaining fallbackUnless call as debt.
      if (ts.isIdentifier(expression) && expression.text === 'fallbackUnless') silent = true;
      if (ts.isPropertyAccessExpression(expression) && expression.name.text === 'catch'
        && callback && ts.isArrowFunction(callback) && callback.parameters.length === 0) silent = true;
      if (silent) {
        const text = node.getText(tree).replace(/\s+/g, ' ');
        const before = source.slice(Math.max(0, node.getStart(tree) - 350), node.getStart(tree));
        const explanation = before.split('\n').slice(-5).join('\n').match(/fallback-ok:\s*([^\n*]{12,})/);
        found.push({
          fingerprint: createHash('sha256').update(text).digest('hex').slice(0, 20),
          line: tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1,
          reason: explanation?.[1].trim() ?? null,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return found;
}

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : path.endsWith('.ts') && !path.endsWith('.spec.ts') ? [path] : [];
  });
}

export function checkBudget(current, budget) {
  const errors = [];
  for (const [file, findings] of Object.entries(current)) {
    const previous = budget.files[file] ?? { count: 0, fingerprints: {} };
    if (findings.length > previous.count) errors.push(`${file}: ${findings.length} fallbacks exceed budget ${previous.count}`);
    const occurrences = {};
    for (const finding of findings) {
      const count = occurrences[finding.fingerprint] = (occurrences[finding.fingerprint] ?? 0) + 1;
      if (count > (previous.fingerprints[finding.fingerprint] ?? 0) && !finding.reason) {
        errors.push(`${file}:${finding.line}: new fallback requires a "fallback-ok: <why an empty value is correct>" comment`);
      }
    }
  }
  return errors;
}

export function checkRatchet(next, previous) {
  const errors = [];
  for (const [file, entry] of Object.entries(next.files)) {
    if (entry.count > (previous.files[file]?.count ?? 0)) errors.push(`${file}: recorded fallback budget may only decrease`);
  }
  return errors;
}

function snapshot(current) {
  return {
    version: 1,
    description: 'Legacy fallbacks are inventoried for migration. A new exception needs a nearby fallback-ok comment explaining why empty is correct; file budgets may only decrease.',
    files: Object.fromEntries(Object.entries(current).filter(([, rows]) => rows.length).map(([file, rows]) => [file, {
      count: rows.length,
      fingerprints: rows.reduce((out, row) => ({ ...out, [row.fingerprint]: (out[row.fingerprint] ?? 0) + 1 }), {}),
    }])),
  };
}

function main(args) {
  const current = Object.fromEntries(files(join(root, 'src/app')).map((path) => [
    relative(root, path).replaceAll('\\', '/'), findFallbacks(readFileSync(path, 'utf8'), path),
  ]));
  if (args.includes('--init')) {
    if (existsSync(budgetPath)) throw new Error('Budget already exists; use --update to reduce it.');
    writeFileSync(budgetPath, JSON.stringify(snapshot(current), null, 2) + '\n');
  }
  if (!existsSync(budgetPath)) throw new Error('Missing fallback budget.');
  const budget = JSON.parse(readFileSync(budgetPath, 'utf8'));
  const errors = checkBudget(current, budget);
  const compareIndex = args.indexOf('--compare-ref');
  if (compareIndex !== -1 && args[compareIndex + 1]) {
    const ref = args[compareIndex + 1];
    // A first introduction has no budget at the merge base. Other git errors fail closed.
    const listed = execFileSync('git', ['ls-tree', ref, '--', 'docs/compliance/fallback-budget.v1.json'], { cwd: resolve(root, '..'), encoding: 'utf8' });
    if (listed.trim()) {
      const previous = JSON.parse(execFileSync('git', ['show', `${ref}:docs/compliance/fallback-budget.v1.json`], { cwd: resolve(root, '..'), encoding: 'utf8' }));
      errors.push(...checkRatchet(budget, previous));
      errors.push(...checkBudget(current, previous));
    }
  }
  if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1; return; }
  if (args.includes('--update')) writeFileSync(budgetPath, JSON.stringify({ ...budget, ...snapshot(current) }, null, 2) + '\n');
  const total = Object.values(current).reduce((sum, rows) => sum + rows.length, 0);
  const allowance = Object.values(budget.files).reduce((sum, entry) => sum + entry.count, 0);
  console.log(`Fallback budget: ${total}/${allowance}; no unreviewed fallback added.`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
