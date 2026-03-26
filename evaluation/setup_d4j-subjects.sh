#!/usr/bin/env bash
OLDIFS=$IFS;

arr_csv=()
while IFS= read -r line
do
    arr_csv+=("$line")
done < <(tail -n +2 d4j-fixed-version.csv)

work_dir="$PWD"
# setup defects4j tag: v2.0.0
git clone https://github.com/rjust/defects4j.git
git checkout 01f13c69425fb8a0db290d12b1d48da1641bf6a9
./init.sh
export D4J_HOME="$work_dir/defects4j"

# download the latest fixed version project from defects4j
subject_dir="$work_dir/defects4j-subjects"
mkdir -p "$subject_dir"

cd "$subject_dir"

IFS=','
for record in "${arr_csv[@]}"; do
  set -- $record
    PID="$2"
    BID="$3"
    echo $PID $BID
    rm -rf "$PID-${BID}f"; "$D4J_HOME/framework/bin/defects4j" checkout -p "$PID" -v "${BID}f" -w "$PID-${BID}f"
done

IFS=$OLDIFS