<?php
header('Content-Type: application/json; charset=utf-8');
$expected = getenv('COURT_KB_API_KEY');
if (!$expected) {
    $envFile = '/home/d/dier555/court-kb-app/.env';
    if (is_readable($envFile)) {
        foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            if ($line[0] === '#' || strpos($line, '=') === false) {
                continue;
            }
            [$k, $v] = explode('=', $line, 2);
            if (trim($k) === 'COURT_KB_API_KEY') {
                $expected = trim($v);
                break;
            }
        }
    }
}
$incoming = $_SERVER['HTTP_X_API_KEY'] ?? '';
if ($expected && !hash_equals($expected, $incoming)) {
    http_response_code(401);
    echo json_encode(['status' => 'error', 'result' => 'Неверный или отсутствующий X-API-Key'], JSON_UNESCAPED_UNICODE);
    exit;
}

$raw = file_get_contents('php://input');
$cmd = '/home/d/dier555/court-kb-app/venv/bin/python /home/d/dier555/court-kb-app/api/run_delo.py';
$descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w'],
];
$proc = proc_open($cmd, $descriptors, $pipes, '/home/d/dier555/court-kb-app', null);
if (!is_resource($proc)) {
    http_response_code(500);
    echo json_encode(['status' => 'error', 'result' => 'Не удалось запустить поиск дела.'], JSON_UNESCAPED_UNICODE);
    exit;
}
fwrite($pipes[0], $raw);
fclose($pipes[0]);
$stdout = stream_get_contents($pipes[1]);
$stderr = stream_get_contents($pipes[2]);
fclose($pipes[1]);
fclose($pipes[2]);
$code = proc_close($proc);
if ($stdout === false || $stdout === '') {
    http_response_code(500);
    echo json_encode(['status' => 'error', 'result' => 'Поиск дела не вернул ответ.', 'debug' => mb_substr($stderr, 0, 300)], JSON_UNESCAPED_UNICODE);
    exit;
}
echo $stdout;
