% batch_mat_to_csv_multifix.m
% The essence of the change: This script will throw away the measurements in the duplicate time samples
clear; clc;

% Directions
in_dir  = fullfile(pwd, 'Tirat Carmel 18-10-25', '11.04.26');  % איפה ה-.mat
out_dir = fullfile(pwd, 'Tirat Carmel 18-10-25', '11.04.26');  % לאן לכתוב .csv

if ~exist(out_dir,'dir')
    [ok,msg] = mkdir(out_dir);
    assert(ok, "Failed to create output folder '%s': %s", out_dir, msg);
end

files = dir(fullfile(in_dir, '*.mat'));
fprintf('📦 Found %d .mat file(s) in %s\n', numel(files), in_dir);

order = {'Acceleration','AngularVelocity','Orientation','Position'}; % סדר הסנסורים

for k = 1:numel(files)
    in_mat = fullfile(files(k).folder, files(k).name);
    fprintf('→ Processing: %s\n', files(k).name);
    try
        S = load(in_mat);

        % וידוא שהטבלאות קיימות
        for r = 1:numel(order)
            assert(isfield(S, order{r}) && istimetable(S.(order{r})), ...
                'Missing timetable: %s', order{r});
        end

        % === חדש: זריקת דגימות כפולות (RowTimes) בכל אחד מהחיישנים ===
        for r = 1:numel(order)
            [S.(order{r}), removed] = dropDuplicateRowTimes(S.(order{r}));
            if removed > 0
                fprintf('   🧹 %s: removed %d duplicate row-time sample(s)\n', order{r}, removed);
            end
        end

        % ציר זמן בסיס (כמו אצלך) + חדש: לוודא שגם הוא ייחודי
        baseTime = getBaseTime(S.Acceleration);
        baseTime = unique(baseTime, 'stable');

        % סנכרון לציר הזמן של התאוצה
        TT = synchronize(S.Acceleration, S.AngularVelocity, S.Orientation, S.Position, ...
                         baseTime, 'linear');

        % פוסט-פרוסס שמות: X_1→Acceleration_X_1 וכו'
        vars  = TT.Properties.VariableNames;
        for i = 1:numel(vars)
            m = regexp(vars{i}, '^(?<base>[^_]+)_(?<idx>[1-9]\d*)$', 'names');
            if ~isempty(m)
                idx = str2double(m.idx);
                if idx>=1 && idx<=numel(order)
                    vars{i} = sprintf('%s_%s_%d', order{idx}, m.base, idx);
                end
            end
        end
        TT.Properties.VariableNames = vars;

        % שם קובץ לפי ה-Timestamp הראשון
        t0    = TT.Properties.RowTimes(1);
        stamp = char(datetime(t0,'Format','dd-MM-yyyy_HH-mm-ss'));
        out_csv = fullfile(out_dir, [stamp '.csv']);

        % דלג אם כבר קיים
        if exist(out_csv,'file')
            fprintf('⏭️  Skip (exists): %s\n', out_csv);
            continue;
        end

        % כתיבה
        writetimetable(TT, out_csv);
        fprintf('✅ Saved: %s\n', out_csv);

    catch ME
        fprintf(2, '❌ Failed: %s\n   %s\n', files(k).name, ME.message);
    end
end

fprintf('🏁 Done.\n');

% ---------- Local helpers ----------
function baseTime = getBaseTime(AccTT)
    % בחלק מהלוגים יש עמודה 'Timestamp', בחלק – ה-RowTimes של הטיימטייבל
    if ismember('Timestamp', AccTT.Properties.VariableNames)
        baseTime = AccTT.Timestamp;
    else
        baseTime = AccTT.Properties.RowTimes;
    end
end

function [TT, removed] = dropDuplicateRowTimes(TT)
    % זורק דגימות עם RowTimes כפולים (שומר את הראשונה)
    if ~issorted(TT.Properties.RowTimes)
        TT = sortrows(TT);
    end
    t = TT.Properties.RowTimes;
    [~, ia] = unique(t, 'stable');
    removed = height(TT) - numel(ia);
    if removed > 0
        TT = TT(ia,:);
    end
end