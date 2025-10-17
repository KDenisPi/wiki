/**
 * @file dict_class.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief Serbice class for dictionary objects (for example instance types etc)
 * @version 0.1
 * @date 2025-09-24
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_DICT_CLASS_H_
#define WIKI_DICT_CLASS_H_

#include <map>
#include <tuple>
#include <string>
#include <cassert>
#include <mutex>
#include <atomic>
#include <fstream>
#include <utility>

namespace wiki{

template<typename K, typename V>
class DictClass{
public:
    DictClass(const std::string& name) : dict_name(name) {
        dict_filename = name + ".csv";
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const int load(const std::string& filename = ""){
        int count = 0;
        save_load_active.store(true);
        const std::lock_guard<std::mutex> lock(mtx);

        std::ifstream inputFile((filename.empty() ? dict_filename : filename));
        if(inputFile.is_open()){
            std::string line;
            while(std::getline(inputFile, line)){
                const auto off = line.find(";");
                const std::string item_id = line.substr(0, off);
                p_dict_exists[item_id] = line.substr(off+1);
                count++;
            }

            inputFile.close();
        }

        save_load_active.store(false);
        std::cout << "Dict load: " << dict_filename << " Loaded: " << p_dict.size() << std::endl;

        return count;
    }

    template <typename Tuple, typename F, std::size_t... I>
    void for_each_impl(Tuple&& t, F&& f, std::index_sequence<I...>) {
        (f(std::get<I>(std::forward<Tuple>(t))), ...); // Fold expression (C++17)
    }

    template <typename Tuple, typename F>
    void for_each(Tuple&& t, F&& f) {
        for_each_impl(std::forward<Tuple>(t), std::forward<F>(f),
                    std::make_index_sequence<std::tuple_size_v<std::decay_t<Tuple>>>{});
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    virtual const bool save(const std::string& filename = ""){
        bool result = true;
        save_load_active.store(true);

        std::cout << "Dict save: " << dict_filename << " Saved: " << p_dict.size() << std::endl;

        std::fstream outputFile((filename.empty() ? dict_filename : filename), std::ios::out | std::ios::app);
        if(outputFile.is_open()){
            outputFile.seekg(0, std::fstream::end);
            for( auto it = p_dict.begin(); it != p_dict.end(); ++it ){
                outputFile << it->first;
                for_each(it->second, [&](const auto& val) {
                    outputFile << ";" << val;
                });
                outputFile << std::endl;
            }
            outputFile.close();
        }
        else
            result = false;

        save_load_active.store(false);
        return result;
    }


    /**
     * @brief
     *
     * @param key
     * @param val
     */
    void put(const K& key, const V& val){
        assert((std::string(typeid(val).name()).find("tuple") != std::string::npos));

        if(save_load_active.load()) //do nothing if we load or save data
            return;

        //check if we have already had this key before
        if( p_dict_exists.size() > 0 && p_dict_exists.end() != p_dict_exists.find(key)){
            return;
        }

        //std::cout << "Dict put: " << key << " Count: " << p_dict.size() << std::endl;

        const std::lock_guard<std::mutex> lock(mtx);
        p_dict[key] = val;
    }


private:
    std::mutex mtx;
    std::map<K,V> p_dict;
    std::map<K,K> p_dict_exists;

    std::string dict_name;
    std::string dict_filename;
    std::atomic_bool save_load_active = false;
};

}//namespace wiki

#endif